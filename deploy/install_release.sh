#!/usr/bin/env bash

set -Eeuo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 RELEASE_ARCHIVE RELEASE_ID [BOT_ROOT]" >&2
  exit 2
fi

release_archive=$1
release_id=$2
bot_root=${3:-/opt/bot_tg}
service_name=${BOT_SERVICE_NAME:-tg-poll-bot}
service_user=${BOT_SERVICE_USER:-tg-poll-bot}
service_group=${BOT_SERVICE_GROUP:-tg-poll-bot}
health_timeout=${BOT_HEALTH_TIMEOUT_SECONDS:-30}
releases_to_keep=${BOT_RELEASES_TO_KEEP:-5}

if [[ ! $release_id =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Release ID contains unsupported characters: $release_id" >&2
  exit 2
fi
if [[ ! -f $release_archive ]]; then
  echo "Release archive not found: $release_archive" >&2
  exit 2
fi

releases_dir=$bot_root/releases
shared_dir=$bot_root/shared
current_link=$bot_root/current
release_dir=$releases_dir/$release_id
next_link=$bot_root/.current-$release_id
previous_target=""
switched=0

if [[ ! -L $current_link ]]; then
  echo "$current_link must already point to the currently working release" >&2
  exit 2
fi

rollback() {
  exit_code=$?
  trap - ERR
  if [[ $switched -eq 1 ]]; then
    echo "Release failed; restoring previous version" >&2
    ln -s "$previous_target" "$next_link"
    mv -Tf "$next_link" "$current_link"
    systemctl restart "$service_name" || true
  fi
  exit "$exit_code"
}
trap rollback ERR

mkdir -p "$releases_dir" "$shared_dir"
if [[ -e $release_dir ]]; then
  echo "Release already exists: $release_dir" >&2
  exit 2
fi

mkdir "$release_dir"
tar --extract --gzip --file "$release_archive" --directory "$release_dir"

python3 -m venv "$release_dir/venv"
"$release_dir/venv/bin/pip" install --quiet --requirement "$release_dir/requirements.txt"
PYTHONPYCACHEPREFIX="$release_dir/.pycache" \
  "$release_dir/venv/bin/python" -m py_compile "$release_dir"/*.py "$release_dir"/deploy/*.py
chown -R "$service_user:$service_group" "$release_dir" "$shared_dir"

previous_target=$(readlink "$current_link")

ln -s "$release_dir" "$next_link"
mv -Tf "$next_link" "$current_link"
switched=1

export BOT_HEALTH_FILE="$shared_dir/health.json"
export BOT_HEALTH_NOT_BEFORE
BOT_HEALTH_NOT_BEFORE=$(date -u +%Y-%m-%dT%H:%M:%S%z)
systemctl restart "$service_name"
systemctl is-active --quiet "$service_name"

for ((attempt = 1; attempt <= health_timeout; attempt++)); do
  if "$current_link/venv/bin/python" "$current_link/deploy/check_bot_health.py"; then
    switched=0
    trap - ERR
    current_target=$(readlink -f "$current_link")
    mapfile -t installed_releases < <(
      find "$releases_dir" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
        | sort -nr \
        | cut -d' ' -f2-
    )
    for ((index = releases_to_keep; index < ${#installed_releases[@]}; index++)); do
      old_release=${installed_releases[$index]}
      if [[ $old_release != "$current_target" ]]; then
        rm -rf -- "$old_release"
      fi
    done
    echo "Release $release_id is healthy"
    exit 0
  fi
  sleep 1
done

echo "Release $release_id did not become healthy in ${health_timeout}s" >&2
false
