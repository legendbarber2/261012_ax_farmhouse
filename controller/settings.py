from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SSHSettings:
    identity_file: str
    connect_timeout_seconds: int = 8
    command_timeout_seconds: int = 90


@dataclass(frozen=True)
class FarmSettings:
    id: str
    name: str
    host: str
    user: str
    project_dir: str
    ptz_enabled: bool = False


@dataclass(frozen=True)
class Settings:
    allowed_users: tuple[str, ...]
    cors_origins: tuple[str, ...]
    dev_auth: bool
    ssh: SSHSettings
    farms: tuple[FarmSettings, ...]

    def farm(self, farm_id: str) -> FarmSettings:
        for farm in self.farms:
            if farm.id == farm_id:
                return farm
        raise KeyError(farm_id)


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(
        path
        or os.environ.get("FARMHOUSE_CONFIG", "")
        or Path(__file__).with_name("config.json")
    )
    if not config_path.is_file():
        raise RuntimeError(
            f"Controller config not found: {config_path}. "
            "Copy controller/config.example.json to controller/config.json."
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    ssh_raw = raw.get("ssh", {})
    ssh = SSHSettings(
        identity_file=_require_text(ssh_raw.get("identity_file"), "ssh.identity_file"),
        connect_timeout_seconds=int(ssh_raw.get("connect_timeout_seconds", 8)),
        command_timeout_seconds=int(ssh_raw.get("command_timeout_seconds", 90)),
    )

    farms: list[FarmSettings] = []
    seen: set[str] = set()
    for index, item in enumerate(raw.get("farms", [])):
        farm_id = _require_text(item.get("id"), f"farms[{index}].id").lower()
        if farm_id in seen:
            raise ValueError(f"Duplicate farm id: {farm_id}")
        if farm_id not in {"gh", "gj", "gs", "ha", "nw"}:
            raise ValueError(f"Unsupported farm id: {farm_id}")
        seen.add(farm_id)
        farms.append(
            FarmSettings(
                id=farm_id,
                name=_require_text(item.get("name"), f"farms[{index}].name"),
                host=_require_text(item.get("host"), f"farms[{index}].host"),
                user=_require_text(item.get("user"), f"farms[{index}].user"),
                project_dir=_require_text(
                    item.get("project_dir"), f"farms[{index}].project_dir"
                ),
                ptz_enabled=bool(item.get("ptz_enabled", False)),
            )
        )
    if not farms:
        raise ValueError("At least one farm must be configured")

    return Settings(
        allowed_users=tuple(str(value) for value in raw.get("allowed_users", [])),
        cors_origins=tuple(str(value).rstrip("/") for value in raw.get("cors_origins", [])),
        dev_auth=bool(raw.get("dev_auth", False)),
        ssh=ssh,
        farms=tuple(farms),
    )

