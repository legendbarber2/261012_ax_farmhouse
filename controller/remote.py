from __future__ import annotations

import base64
import json
import re
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


def validate_session_id(session_id: str) -> None:
    if not re.fullmatch(r"[SC]20\d{6}T\d{6}Z-[A-Z0-9_-]{4,64}", session_id):
        raise ValueError("Invalid session id")


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

    def list_sessions(
        self,
        farm: FarmSettings,
        *,
        camera: str | None,
        data_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        camera_literal = json.dumps(camera or "")
        type_literal = json.dumps(data_type or "")
        script = f"""
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path({json.dumps(farm.project_dir)})
camera_filter = {camera_literal}
type_filter = {type_literal}
roots = []
if type_filter in ('', 'farm_work'):
    roots.append(('farm_work', root / 'data' / 'farm_work'))
if type_filter in ('', 'crop'):
    roots.append(('crop', root / 'data' / 'crop'))

grouped = {{}}
for kind, base in roots:
    if not base.exists():
        continue
    for manifest_path in base.glob('*/*/*/*/*/CAM*/session.json'):
        session_dir = manifest_path.parent.parent
        key = (kind, session_dir.as_posix())
        grouped.setdefault(key, []).append(manifest_path)

rows = []
for (kind, session_path_text), manifest_paths in grouped.items():
    session_path = Path(session_path_text)
    records = []
    for manifest_path in sorted(manifest_paths):
        try:
            record = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        records.append(record)
    if not records:
        continue
    by_camera = {{record.get('camera_id'): record for record in records}}
    if camera_filter:
        selected = by_camera.get(camera_filter)
        if not selected or int(selected.get('capture_count') or 0) <= 0:
            continue
    started_values = [record.get('started_at') for record in records if record.get('started_at')]
    ended_values = [record.get('ended_at') for record in records if record.get('ended_at')]
    started_at = min(started_values) if started_values else None
    ended_at = max(ended_values) if ended_values else None
    try:
        sort_value = datetime.fromisoformat(started_at).timestamp() if started_at else session_path.stat().st_mtime
    except (ValueError, OSError):
        sort_value = 0
    statuses = {{str(record.get('status') or 'unknown') for record in records}}
    if 'recording' in statuses:
        status = 'recording'
    elif 'interrupted' in statuses:
        status = 'interrupted'
    elif statuses == {{'completed'}} and len(records) == 3:
        status = 'completed'
    else:
        status = 'partial'
    rows.append({{
        'data_type': kind,
        'session_id': session_path.name,
        'session_path': session_path.as_posix(),
        'records': records,
        'started_at': started_at,
        'ended_at': ended_at,
        'status': status,
        'sort_value': sort_value,
    }})

rows.sort(key=lambda item: item['sort_value'], reverse=True)
total = len(rows)
page = rows[{offset}:{offset + limit}]
items = []
for row in page:
    session_path = Path(row.pop('session_path'))
    records = row.pop('records')
    by_camera = {{record.get('camera_id'): record for record in records}}
    cameras = []
    representatives = []
    trigger_cameras = []
    total_captures = 0
    for camera_id in ('CAM01', 'CAM02', 'CAM03'):
        record = by_camera.get(camera_id, {{}})
        capture_count = int(record.get('capture_count') or 0)
        total_captures += capture_count
        representative = None
        image_dir = session_path / camera_id / 'images'
        image_paths = sorted(image_dir.glob('*.jpg')) if image_dir.exists() else []
        if image_paths:
            image_path = image_paths[0]
            metadata = {{}}
            try:
                metadata = json.loads(image_path.with_suffix('.json').read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                pass
            detections = metadata.get('detections') or []
            if detections:
                trigger_cameras.append(camera_id)
            stat = image_path.stat()
            representative = {{
                'path': image_path.relative_to(root).as_posix(),
                'camera_id': camera_id,
                'captured_at': stat.st_mtime,
                'size_bytes': stat.st_size,
                'person_detected': bool(detections),
            }}
            if not camera_filter or camera_filter == camera_id:
                representatives.append(representative)
        cameras.append({{
            'camera_id': camera_id,
            'capture_count': capture_count,
            'status': record.get('status') or 'missing',
            'started_with_person': bool(representative and representative['person_detected']),
        }})
    review_flags = []
    if row['status'] != 'completed':
        review_flags.append('incomplete')
    if any(camera['capture_count'] == 0 for camera in cameras):
        review_flags.append('missing_camera')
    if row['data_type'] == 'farm_work' and not trigger_cameras:
        review_flags.append('no_start_detection')
    duration_seconds = None
    if row['started_at'] and row['ended_at']:
        try:
            duration_seconds = max(0, (datetime.fromisoformat(row['ended_at']) - datetime.fromisoformat(row['started_at'])).total_seconds())
        except ValueError:
            pass
    items.append({{
        **row,
        'duration_seconds': duration_seconds,
        'capture_count': total_captures,
        'trigger_cameras': trigger_cameras,
        'review_flags': review_flags,
        'cameras': cameras,
        'representatives': representatives,
    }})

print(json.dumps({{'total': total, 'items': items}}, ensure_ascii=False))
""".strip()
        command = f"python3 - <<'PY'\n{script}\nPY"
        result = self.run(farm, command)
        assert isinstance(result, RemoteResult)
        payload = json.loads(result.stdout)
        for session in payload["items"]:
            for item in session["representatives"]:
                item["id"] = encode_image_id(item.pop("path"))
        return payload

    def list_session_images(
        self,
        farm: FarmSettings,
        *,
        session_id: str,
        data_type: str,
        camera: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        validate_session_id(session_id)
        if data_type not in {"farm_work", "crop"}:
            raise ValueError("Unsupported data type")
        if camera is not None and camera not in {"CAM01", "CAM02", "CAM03"}:
            raise ValueError("Unsupported camera id")
        script = f"""
import json
from pathlib import Path

root = Path({json.dumps(farm.project_dir)})
base = root / 'data' / {json.dumps(data_type)}
session_id = {json.dumps(session_id)}
camera_filter = {json.dumps(camera or '')}
session_dirs = [path for path in base.glob('*/*/*/*/' + session_id) if path.is_dir()]
items = []
if session_dirs:
    session_dir = session_dirs[0]
    for path in session_dir.glob('CAM*/images/*.jpg'):
        camera_id = path.parent.parent.name
        if camera_filter and camera_id != camera_filter:
            continue
        metadata = {{}}
        try:
            metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            pass
        stat = path.stat()
        items.append({{
            'path': path.relative_to(root).as_posix(),
            'camera_id': camera_id,
            'data_type': {json.dumps(data_type)},
            'session_id': session_id,
            'captured_at': stat.st_mtime,
            'size_bytes': stat.st_size,
            'filename': path.name,
            'person_detected': bool(metadata.get('detections')),
            'detection_count': len(metadata.get('detections') or []),
        }})
items.sort(key=lambda item: (item['captured_at'], item['camera_id']))
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

    def preview(self, farm: FarmSettings, camera: str) -> bytes:
        if camera not in {"CAM01", "CAM02", "CAM03"}:
            raise ValueError("Unsupported camera id")
        project = self._project(farm)
        result = self.run(
            farm,
            (
                f"cd {project} && scripts/capture-camera-preview.sh "
                f"--camera {shlex.quote(camera)}"
            ),
            binary=True,
            timeout=30,
        )
        assert isinstance(result, bytes)
        if not result.startswith(b"\xff\xd8") or not result.endswith(b"\xff\xd9"):
            raise RemoteError("Camera preview did not return a valid JPEG")
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
