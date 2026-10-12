import json

import pytest

from controller.settings import load_settings


def write_config(tmp_path, farms):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "allowed_users": ["operator@example.com"],
                "cors_origins": ["https://example.github.io/"],
                "dev_auth": True,
                "ssh": {"identity_file": "/tmp/key"},
                "farms": farms,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_load_settings(tmp_path):
    path = write_config(
        tmp_path,
        [
            {
                "id": "ha",
                "name": "HA 농가",
                "host": "100.64.0.1",
                "user": "theimc-ha",
                "project_dir": "/home/theimc-ha/farm-camera",
            }
        ],
    )
    settings = load_settings(path)
    assert settings.farm("ha").name == "HA 농가"
    assert settings.cors_origins == ("https://example.github.io",)


def test_rejects_duplicate_farms(tmp_path):
    farm = {
        "id": "ha",
        "name": "HA 농가",
        "host": "100.64.0.1",
        "user": "theimc-ha",
        "project_dir": "/home/theimc-ha/farm-camera",
    }
    path = write_config(tmp_path, [farm, farm])
    with pytest.raises(ValueError, match="Duplicate farm id"):
        load_settings(path)

