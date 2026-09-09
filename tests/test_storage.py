import json

import pytest

from storage import JsonStateRepository, StateLoadError


def test_atomic_save_and_load(tmp_path):
    repository = JsonStateRepository(str(tmp_path / "state.json"))

    repository.save({"schema_version": 1, "value": "первое"})

    assert repository.load() == {"schema_version": 1, "value": "первое"}
    assert (tmp_path / "state.json").stat().st_mode & 0o777 == 0o600


def test_previous_valid_state_becomes_backup(tmp_path):
    repository = JsonStateRepository(str(tmp_path / "state.json"))
    repository.save({"value": 1})

    repository.save({"value": 2})

    assert json.loads((tmp_path / "state.json.bak").read_text()) == {"value": 1}
    assert repository.load() == {"value": 2}


def test_load_recovers_from_backup(tmp_path):
    repository = JsonStateRepository(str(tmp_path / "state.json"))
    repository.save({"value": 1})
    repository.save({"value": 2})
    (tmp_path / "state.json").write_text("{broken", encoding="utf-8")

    assert repository.load() == {"value": 1}
    assert repository.recovered_from_backup is True


def test_load_fails_when_state_and_backup_are_broken(tmp_path):
    repository = JsonStateRepository(str(tmp_path / "state.json"))
    repository.path.write_text("{broken", encoding="utf-8")
    repository.backup_path.write_text("{also-broken", encoding="utf-8")

    with pytest.raises(StateLoadError):
        repository.load()
