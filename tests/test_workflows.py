import re
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def test_workflows_are_valid_yaml():
    for path in WORKFLOW_DIR.glob("*.yml"):
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict), path
        assert "jobs" in parsed, path


def test_external_actions_are_pinned_to_commit_sha():
    action_pattern = re.compile(r"^\s*uses:\s*([^#\s]+)", re.MULTILINE)
    for path in WORKFLOW_DIR.glob("*.yml"):
        actions = action_pattern.findall(path.read_text(encoding="utf-8"))
        for action in actions:
            reference = action.rsplit("@", 1)[-1]
            assert re.fullmatch(r"[0-9a-f]{40}", reference), f"{path}: {action}"
