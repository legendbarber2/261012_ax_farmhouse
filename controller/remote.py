from __future__ import annotations

import base64
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .settings import FarmSettings, SSHSettings


class RemoteError(RuntimeError):
    def __init__(self, message: str, *, returncode: int | None = None):
        super().__init__(message)
        self.returncode = returncode


@dataclass(frozen=True)
class RemoteResult:
    stdout: str
    stderr: str
    returncode: int


def encode_image_id(path: str) -> str:
    return base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii").rstrip("=")


def decode_image_id(image_id: str) -> str:
    try:
        padding = "=" * (-len(image_id) % 4)
        value = base64.urlsafe_b64decode(image_id + padding).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - malformed user input
        raise ValueError("Invalid image id") from exc
    validate_image_path(value)
    return value


def validate_image_path(path: str) -> None:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Invalid image path")
    if candidate.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("Unsupported image type")
    prefixes = (("data", "farm_work"), ("data", "crop"))
    if not any(candidate.parts[:2] == prefix for prefix in prefixes):
        raise ValueError("Image path is outside an allowed data directory")


class SSHFarmClient:
    def __init__(self, ssh: SSHSettings):
        self.ssh = ssh

    def _base_args(self, farm: FarmSettings) -> list[str]:
        return [
            "ssh",
            "-i",
            self.ssh.identity_file,
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.ssh.connect_timeout_seconds}",
            "-o",
            "ServerAliveInterval=5",
            "-o",
            "ServerAliveCountMax=2",
            f"{farm.user}@{farm.host}",
        ]

    def run(
        self,
        farm: FarmSettings,
        command: str,
        *,
        timeout: int | None = None,
        check: bool = True,
        binary: bool = False,
    ) -> RemoteResult | bytes:
        try:
            completed = subprocess.run(
                [*self._base_args(farm), command],
                capture_output=True,
                text=not binary,
                timeout=timeout or self.ssh.command_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RemoteError(f"Remote command timed out for {farm.id}") from exc
        if check and completed.returncode != 0:
            stderr = completed.stderr.decode() if binary else completed.stderr
            detail = (stderr or "remote command failed").strip()
            raise RemoteError(detail, returncode=completed.returncode)
        if binary:
            return completed.stdout
        return RemoteResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )

    @staticmethod
    def _project(farm: FarmSettings) -> str:
        return shlex.quote(farm.project_dir)

    def status(self, farm: FarmSettings) -> dict[str, Any]:
        project = self._project(farm)
        command = f"""
cd {project}
scripts/check-operational-status.sh >/dev/null 2>&1 || true
printf '%s\\n' '__REPORT__'
cat data/health/operational-status-latest.json
printf '%s\\n' '__SERVICES__'
for unit in farm-camera-collect.service farm-camera-crop.timer farm-camera-upload.timer; do
  printf '%s=' "$unit"
  systemctl is-active "$unit" 2>/dev/null || true
done
""".strip()
        result = self.run(farm, command)
        assert isinstance(result, RemoteResult)
        try:
            report_text, services_text = result.stdout.split("__SERVICES__\n", 1)
            report_text = report_text.split("__REPORT__\n", 1)[1]
            report = json.loads(report_text)
        except (ValueError, IndexError, json.JSONDecodeError) as exc:
            raise RemoteError(f"Could not parse status report for {farm.id}") from exc
        services = {}
        for line in services_text.splitlines():
            if "=" in line:
                unit, state = line.split("=", 1)
                services[unit] = state
        return {
            "id": farm.id,
            "name": farm.name,
            "online": True,
            "ptz_enabled": farm.ptz_enabled,
            "report": report,
            "services": services,
        }

    def list_images(
        self,
        farm: FarmSettings,
        *,
        camera: str | None,
        data_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        project = self._project(farm)
        camera_literal = json.dumps(camera or "")
        type_literal = json.dumps(data_type or "")
        script = f"""
import json
from pathlib import Path

root = Path({json.dumps(farm.project_dir)})
camera_filter = {camera_literal}
type_filter = {type_literal}
items = []
roots = []
if type_filter in ('', 'farm_work'):
    roots.append(('farm_work', root / 'data' / 'farm_work'))
if type_filter in ('', 'crop'):
    roots.append(('crop', root / 'data' / 'crop'))
for kind, base in roots:
    if not base.exists():
        continue
    for path in base.rglob('*.jpg'):
        rel = path.relative_to(root).as_posix()
        camera_id = next((part for part in path.parts if part in ('CAM01', 'CAM02', 'CAM03')), '')
        if camera_filter and camera_id != camera_filter:
            continue
        stat = path.stat()
        session_id = next((part for part in path.parts if part.startswith(('S20', 'C20'))), None)
        items.append({{
            'path': rel,
            'camera_id': camera_id,
            'data_type': kind,
            'session_id': session_id,
            'captured_at': stat.st_mtime,
            'size_bytes': stat.st_size,
            'filename': path.name,
        }})
items.sort(key=lambda item: item['captured_at'], reverse=True)
print(json.dumps({{'total': len(items), 'items': items[{offset}:{offset + limit}]}}, ensure_ascii=False))
""".strip()
        command = f"python3 - <<'PY'\n{script}\nPY"
        result = self.run(farm, command)
        assert isinstance(result, RemoteResult)
        payload = json.loads(result.stdout)
        for item in payload["items"]:
            item["id"] = encode_image_id(item.pop("path"))
        return payload

    def image(self, farm: FarmSettings, image_id: str) -> bytes:
        relative = decode_image_id(image_id)
        project = PurePosixPath(farm.project_dir)
        full_path = (project / relative).as_posix()
        result = self.run(
            farm,
            f"cat -- {shlex.quote(full_path)}",
            binary=True,
            timeout=30,
        )
        assert isinstance(result, bytes)
        return result

    def action(self, farm: FarmSettings, action: str) -> RemoteResult:
        project = self._project(farm)
        commands = {
            "capture": f"cd {project} && scripts/run-crop-capture.sh",
            "upload": (
                f"cd {project} && "
                "scripts/upload-all-completed-sessions.sh --batch-mode"
            ),
            "restart": "sudo -n systemctl restart farm-camera-collect.service",
            "check": f"cd {project} && scripts/04-check-farm-operation.sh",
        }
        if action not in commands:
            raise ValueError(f"Unsupported action: {action}")
        result = self.run(
            farm,
            commands[action],
            timeout=300 if action == "upload" else 120,
        )
        assert isinstance(result, RemoteResult)
        return result

    def logs(self, farm: FarmSettings, unit: str, lines: int) -> str:
        allowed = {
            "collect": "farm-camera-collect.service",
            "crop": "farm-camera-crop.service",
            "upload": "farm-camera-upload.service",
        }
        if unit not in allowed:
            raise ValueError("Unsupported log unit")
        command = f"journalctl -u {allowed[unit]} -n {lines} --no-pager 2>&1"
        result = self.run(farm, command, timeout=30)
        assert isinstance(result, RemoteResult)
        return result.stdout

    def ptz(
        self,
        farm: FarmSettings,
        *,
        camera: str,
        direction: str,
        speed: float,
        duration: float,
    ) -> RemoteResult:
        if not farm.ptz_enabled:
            raise RemoteError("PTZ is not enabled for this farm")
        project = self._project(farm)
        command = (
            f"cd {project} && scripts/control-camera-ptz.sh "
            f"--camera {shlex.quote(camera)} "
            f"--direction {shlex.quote(direction)} "
            f"--speed {speed:.2f} --duration {duration:.2f}"
        )
        result = self.run(farm, command, timeout=30)
        assert isinstance(result, RemoteResult)
        return result

