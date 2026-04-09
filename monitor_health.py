import json
import os
import smtplib
import ssl
import subprocess
import time
from email.message import EmailMessage
from pathlib import Path
from urllib import error, parse, request

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = os.getenv("MONITOR_ENV_FILE", ".env.monitor")
ENV_PATH = BASE_DIR / ENV_FILE
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else value


def _normalize_id(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "target"
    out = []
    for ch in raw:
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("-")
    normalized = "".join(out).strip("-")
    return normalized or "target"


def check_url(url: str, timeout: int = 10) -> tuple[bool, str]:
    try:
        req = request.Request(url, headers={"User-Agent": "uptime-monitor/1.0"})
        with request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if 200 <= status < 400:
                return True, f"ok ({status})"
            return False, f"bad status ({status})"
    except error.URLError as exc:
        return False, f"url error: {exc}"
    except Exception as exc:
        return False, f"error: {exc}"


def check_systemd_service(service_name: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        state = (proc.stdout or proc.stderr).strip()
        if proc.returncode == 0 and state == "active":
            return True, "active"
        return False, state or f"exit={proc.returncode}"
    except Exception as exc:
        return False, f"error: {exc}"


def read_bot_token_from_env_file(env_file: Path) -> str:
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def read_env_value(env_file: Path, key: str) -> str:
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def check_telegram_bot(token: str, timeout: int = 10) -> tuple[bool, str]:
    if not token:
        return False, "missing token"
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            if data.get("ok"):
                return True, "getMe ok"
            return False, f"telegram not ok: {data}"
    except Exception as exc:
        return False, f"error: {exc}"


def load_targets(bot_env_file: Path) -> list[dict]:
    targets_path = _env("MONITOR_TARGETS_FILE")
    if targets_path:
        path = Path(targets_path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("MONITOR_TARGETS_FILE must contain a JSON array")
            targets: list[dict] = []
            for idx, item in enumerate(data, 1):
                if not isinstance(item, dict):
                    continue
                target_id = _normalize_id(str(item.get("id") or f"target-{idx}"))
                name = str(item.get("name") or target_id)
                repo = str(item.get("repo") or "-")
                target_type = str(item.get("type") or "").strip()
                target: dict = {
                    "id": target_id,
                    "name": name,
                    "repo": repo,
                    "type": target_type,
                }

                if target_type == "url":
                    target["url"] = str(item.get("url") or "")
                elif target_type == "systemd":
                    target["service"] = str(item.get("service") or "")
                elif target_type == "telegram_getme":
                    token = str(item.get("token") or "")
                    token_env = str(item.get("token_env") or "")
                    token_env_file_key = str(item.get("token_env_file_key") or "")
                    if not token and token_env:
                        token = _env(token_env)
                    if not token and token_env_file_key:
                        token = read_env_value(bot_env_file, token_env_file_key)
                    target["token"] = token
                else:
                    continue
                targets.append(target)
            if targets:
                return targets

    website_url = _env("WEBSITE_URL", "https://craftboard.online")
    website_repo = _env("WEBSITE_REPO", "keastayer-cell/craftboard-site")
    service_name = _env("BOT_SYSTEMD_SERVICE", "tg-poll-bot")
    bot_repo = _env("BOT_REPO", "keastayer-cell/tg-poll-bot")

    bot_token = _env("BOT_TOKEN") or read_bot_token_from_env_file(bot_env_file)

    return [
        {
            "id": "website-main",
            "name": "Craftboard website",
            "repo": website_repo,
            "type": "url",
            "url": website_url,
        },
        {
            "id": "bot-systemd",
            "name": f"Bot service {service_name}",
            "repo": bot_repo,
            "type": "systemd",
            "service": service_name,
        },
        {
            "id": "bot-telegram-api",
            "name": "Bot Telegram API",
            "repo": bot_repo,
            "type": "telegram_getme",
            "token": bot_token,
        },
    ]


def run_target_check(target: dict, timeout: int) -> tuple[bool, str]:
    target_type = target.get("type")
    if target_type == "url":
        return check_url(str(target.get("url", "")), timeout=timeout)
    if target_type == "systemd":
        return check_systemd_service(str(target.get("service", "")))
    if target_type == "telegram_getme":
        return check_telegram_bot(str(target.get("token", "")), timeout=timeout)
    return False, f"unsupported type: {target_type}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def send_email(subject: str, body: str) -> None:
    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "465"))
    username = _env("SMTP_USERNAME")
    password = _env("SMTP_PASSWORD")
    from_email = _env("ALERT_FROM") or username
    to_emails = [x.strip() for x in _env("ALERT_TO").split(",") if x.strip()]

    if not (host and username and password and from_email and to_emails):
        print("[monitor] SMTP/recipient not configured, skip email")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(to_emails)
    msg.set_content(body)

    use_tls = _env("SMTP_TLS", "1").lower() not in {"0", "false", "no"}
    if use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(username, password)
            server.send_message(msg)


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    if not token or not chat_id:
        print("[monitor] Telegram recipient not configured, skip telegram")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = parse.urlencode({"chat_id": chat_id, "text": text})
    req = request.Request(url, data=payload.encode("utf-8"), method="POST")
    try:
        with request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            return bool(data.get("ok"))
    except Exception as exc:
        print(f"[monitor] Telegram send failed: {exc}")
        return False


def notify(subject: str, body: str, token: str, chat_id: str) -> None:
    # Prefer Telegram for simpler setup; email is optional fallback/additional channel.
    text = f"{subject}\n\n{body}"
    sent_telegram = send_telegram(token, chat_id, text)
    send_email(subject, body)
    if not sent_telegram:
        print("[monitor] Telegram notification was not sent")


def format_target_line(target: dict, details: str) -> str:
    target_id = target.get("id", "target")
    name = target.get("name", target_id)
    repo = target.get("repo", "-")
    target_type = target.get("type", "-")
    endpoint = "-"
    if target_type == "url" and target.get("url"):
        endpoint = str(target.get("url"))
    if target_type == "systemd" and target.get("service"):
        endpoint = str(target.get("service"))
    return (
        f"- Service: {name}\n"
        f"  ID: {target_id}\n"
        f"  Repo: {repo}\n"
        f"  Check: {target_type}\n"
        f"  Target: {endpoint}\n"
        f"  Details: {details}"
    )


def build_subject(prefix: str, ids: list[str], targets_map: dict[str, dict]) -> str:
    names = [targets_map.get(i, {}).get("name", i) for i in ids]
    if not names:
        return f"[{prefix}] no changes"
    if len(names) == 1:
        return f"[{prefix}] {names[0]}"
    head = ", ".join(names[:2])
    tail = "" if len(names) <= 2 else f" +{len(names) - 2} more"
    return f"[{prefix} x{len(names)}] {head}{tail}"


def main() -> int:
    checks: dict[str, tuple[bool, str]] = {}
    timeout = int(_env("HTTP_TIMEOUT", "10"))
    bot_env_file = Path(_env("BOT_ENV_FILE", "/opt/bot_tg/.env"))
    targets = load_targets(bot_env_file)
    targets_map = {t["id"]: t for t in targets}
    for target in targets:
        checks[target["id"]] = run_target_check(target, timeout)

    bot_token = _env("BOT_TOKEN") or read_bot_token_from_env_file(bot_env_file)
    alert_token = _env("ALERT_BOT_TOKEN") or bot_token
    alert_chat_id = _env("ALERT_TELEGRAM_CHAT_ID")
    if not alert_chat_id:
        alert_chat_id = read_env_value(bot_env_file, "ADMIN_ID")

    state_file = Path(_env("MONITOR_STATE_FILE", "/var/lib/uptime-monitor/state.json"))
    prev = load_state(state_file)
    current = {name: {"ok": ok, "details": details} for name, (ok, details) in checks.items()}

    failed_now = [name for name, (ok, _) in checks.items() if not ok]
    failed_prev = [name for name, info in prev.items() if not info.get("ok", False)]

    became_down = sorted(set(failed_now) - set(failed_prev))
    became_up = sorted(set(failed_prev) - set(failed_now))

    hostname = _env("MONITOR_NAME") or os.uname().nodename
    ts = time.strftime("%Y-%m-%d %H:%M:%S %Z")

    if became_down:
        lines = [f"[{ts}] {hostname}: detected DOWN targets"]
        for target_id in became_down:
            target = targets_map.get(target_id, {"id": target_id, "name": target_id, "repo": "-", "type": "-"})
            lines.append(format_target_line(target, str(current[target_id]["details"])))
        notify(build_subject("ALERT DOWN", became_down, targets_map), "\n\n".join(lines), alert_token, alert_chat_id)

    if became_up:
        lines = [f"[{ts}] {hostname}: recovered targets"]
        for target_id in became_up:
            target = targets_map.get(target_id, {"id": target_id, "name": target_id, "repo": "-", "type": "-"})
            details = current.get(target_id, {}).get("details") or prev.get(target_id, {}).get("details") or "ok"
            lines.append(format_target_line(target, str(details)))
        notify(build_subject("RECOVERY", became_up, targets_map), "\n\n".join(lines), alert_token, alert_chat_id)

    save_state(state_file, current)

    for target_id, (ok, details) in checks.items():
        status = "OK" if ok else "FAIL"
        target = targets_map.get(target_id, {"name": target_id, "repo": "-", "type": "-"})
        print(f"{status} {target.get('name')} | repo={target.get('repo')} | type={target.get('type')} | {details}")

    return 0 if not failed_now else 1


if __name__ == "__main__":
    raise SystemExit(main())
