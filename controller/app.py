from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .remote import RemoteError, RemoteResult, SSHFarmClient
from .settings import FarmSettings, Settings, load_settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PTZRequest(BaseModel):
    camera: Literal["CAM01", "CAM02", "CAM03"]
    direction: Literal["up", "down", "left", "right", "stop", "home"]
    speed: float = Field(default=0.5, ge=0.1, le=1.0)
    duration: float = Field(default=0.4, ge=0.1, le=2.0)


class JobStore:
    def __init__(self, client: SSHFarmClient, max_workers: int = 5):
        self.client = client
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.farm_locks: dict[str, threading.Lock] = {}

    def submit_action(
        self,
        farm: FarmSettings,
        action: str,
        *,
        ptz: PTZRequest | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "farm_id": farm.id,
            "action": action,
            "status": "queued",
            "created_at": utc_now(),
            "started_at": None,
            "finished_at": None,
            "output": "",
            "error": None,
        }
        with self.lock:
            self.jobs[job_id] = job
            farm_lock = self.farm_locks.setdefault(farm.id, threading.Lock())
        self.executor.submit(self._run, job_id, farm, action, farm_lock, ptz)
        return dict(job)

    def _run(
        self,
        job_id: str,
        farm: FarmSettings,
        action: str,
        farm_lock: threading.Lock,
        ptz: PTZRequest | None,
    ) -> None:
        self._update(job_id, status="running", started_at=utc_now())
        try:
            with farm_lock:
                if ptz is not None:
                    result = self.client.ptz(farm, **ptz.model_dump())
                else:
                    result = self.client.action(farm, action)
            output = "\n".join(value for value in (result.stdout, result.stderr) if value)
            self._update(
                job_id,
                status="succeeded",
                finished_at=utc_now(),
                output=output[-20_000:],
            )
        except Exception as exc:  # noqa: BLE001 - job result must capture remote failures
            self._update(
                job_id,
                status="failed",
                finished_at=utc_now(),
                error=str(exc),
            )

    def _update(self, job_id: str, **values: Any) -> None:
        with self.lock:
            self.jobs[job_id].update(values)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None


def create_app(
    settings: Settings | None = None,
    client: SSHFarmClient | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    client = client or SSHFarmClient(settings.ssh)
    jobs = JobStore(client)

    app = FastAPI(
        title="AX Farmhouse Controller",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.client = client
    app.state.jobs = jobs

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )

    def require_user(request: Request) -> str:
        client_host = request.client.host if request.client else ""
        if settings.dev_auth and client_host in {"127.0.0.1", "::1", "testclient"}:
            return "local-development"
        login = request.headers.get("Tailscale-User-Login", "").strip()
        if not login:
            raise HTTPException(
                status_code=401,
                detail="Access the API through Tailscale Serve.",
            )
        if settings.allowed_users and login not in settings.allowed_users:
            raise HTTPException(status_code=403, detail="Tailscale user is not allowed.")
        return login

    def farm_or_404(farm_id: str) -> FarmSettings:
        try:
            return settings.farm(farm_id.lower())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Farm not found") from exc

    @app.get("/api/health")
    def health(user: str = Depends(require_user)) -> dict[str, Any]:
        return {
            "status": "ok",
            "user": user,
            "generated_at": utc_now(),
            "farm_count": len(settings.farms),
        }

    @app.get("/api/farms")
    def farms(user: str = Depends(require_user)) -> dict[str, Any]:
        del user
        return {
            "farms": [
                {
                    "id": farm.id,
                    "name": farm.name,
                    "ptz_enabled": farm.ptz_enabled,
                }
                for farm in settings.farms
            ]
        }

    @app.get("/api/dashboard")
    def dashboard(user: str = Depends(require_user)) -> dict[str, Any]:
        del user
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(5, len(settings.farms))) as executor:
            futures = {executor.submit(client.status, farm): farm for farm in settings.farms}
            for future in as_completed(futures):
                farm = futures[future]
                try:
                    results[farm.id] = future.result()
                except Exception as exc:  # noqa: BLE001 - offline farm is valid dashboard state
                    results[farm.id] = {
                        "id": farm.id,
                        "name": farm.name,
                        "online": False,
                        "ptz_enabled": farm.ptz_enabled,
                        "error": str(exc),
                        "report": None,
                        "services": {},
                    }
        return {
            "generated_at": utc_now(),
            "farms": [results[farm.id] for farm in settings.farms],
        }

    @app.get("/api/farms/{farm_id}/status")
    def farm_status(
        farm_id: str,
        user: str = Depends(require_user),
    ) -> dict[str, Any]:
        del user
        farm = farm_or_404(farm_id)
        try:
            return client.status(farm)
        except RemoteError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/farms/{farm_id}/images")
    def images(
        farm_id: str,
        camera: Literal["CAM01", "CAM02", "CAM03"] | None = None,
        data_type: Literal["farm_work", "crop"] | None = None,
        limit: int = Query(default=24, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        user: str = Depends(require_user),
    ) -> dict[str, Any]:
        del user
        farm = farm_or_404(farm_id)
        try:
            payload = client.list_images(
                farm,
                camera=camera,
                data_type=data_type,
                limit=limit,
                offset=offset,
            )
        except (RemoteError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        for item in payload["items"]:
            item["url"] = f"/api/farms/{farm.id}/images/{item['id']}"
        payload.update({"farm_id": farm.id, "limit": limit, "offset": offset})
        return payload

    @app.get("/api/farms/{farm_id}/sessions")
    def sessions(
        farm_id: str,
        camera: Literal["CAM01", "CAM02", "CAM03"] | None = None,
        data_type: Literal["farm_work", "crop"] | None = None,
        limit: int = Query(default=8, ge=1, le=50),
        offset: int = Query(default=0, ge=0),
        user: str = Depends(require_user),
    ) -> dict[str, Any]:
        del user
        farm = farm_or_404(farm_id)
        try:
            payload = client.list_sessions(
                farm,
                camera=camera,
                data_type=data_type,
                limit=limit,
                offset=offset,
            )
        except (RemoteError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        for session in payload["items"]:
            for item in session["representatives"]:
                item["url"] = f"/api/farms/{farm.id}/images/{item['id']}"
        payload.update({"farm_id": farm.id, "limit": limit, "offset": offset})
        return payload

    @app.get("/api/farms/{farm_id}/sessions/{session_id}/images")
    def session_images(
        farm_id: str,
        session_id: str,
        data_type: Literal["farm_work", "crop"],
        camera: Literal["CAM01", "CAM02", "CAM03"] | None = None,
        limit: int = Query(default=60, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        user: str = Depends(require_user),
    ) -> dict[str, Any]:
        del user
        farm = farm_or_404(farm_id)
        try:
            payload = client.list_session_images(
                farm,
                session_id=session_id,
                data_type=data_type,
                camera=camera,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RemoteError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        for item in payload["items"]:
            item["url"] = f"/api/farms/{farm.id}/images/{item['id']}"
        payload.update(
            {
                "farm_id": farm.id,
                "session_id": session_id,
                "data_type": data_type,
                "limit": limit,
                "offset": offset,
            }
        )
        return payload

    @app.get("/api/farms/{farm_id}/preview")
    def preview(
        farm_id: str,
        camera: Literal["CAM01", "CAM02", "CAM03"],
        user: str = Depends(require_user),
    ) -> Response:
        del user
        farm = farm_or_404(farm_id)
        try:
            content = client.preview(farm, camera)
        except (RemoteError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/farms/{farm_id}/images/{image_id}")
    def image(
        farm_id: str,
        image_id: str,
        download: bool = False,
        user: str = Depends(require_user),
    ) -> Response:
        del user
        farm = farm_or_404(farm_id)
        try:
            content = client.image(farm, image_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RemoteError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        headers = {"Cache-Control": "private, max-age=60"}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{image_id}.jpg"'
        return Response(content=content, media_type="image/jpeg", headers=headers)

    @app.post("/api/farms/{farm_id}/actions/{action}", status_code=202)
    def action(
        farm_id: str,
        action: Literal["capture", "upload", "restart", "check"],
        user: str = Depends(require_user),
    ) -> dict[str, Any]:
        del user
        farm = farm_or_404(farm_id)
        return jobs.submit_action(farm, action)

    @app.post("/api/farms/{farm_id}/ptz", status_code=202)
    def ptz(
        farm_id: str,
        request_body: PTZRequest,
        user: str = Depends(require_user),
    ) -> dict[str, Any]:
        del user
        farm = farm_or_404(farm_id)
        if not farm.ptz_enabled:
            raise HTTPException(
                status_code=409,
                detail="PTZ is not configured on this farm PC yet.",
            )
        return jobs.submit_action(farm, "ptz", ptz=request_body)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str, user: str = Depends(require_user)) -> dict[str, Any]:
        del user
        value = jobs.get(job_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return value

    @app.get("/api/farms/{farm_id}/logs")
    def logs(
        farm_id: str,
        unit: Literal["collect", "crop", "upload"] = "collect",
        lines: int = Query(default=100, ge=10, le=500),
        user: str = Depends(require_user),
    ) -> dict[str, Any]:
        del user
        farm = farm_or_404(farm_id)
        try:
            output = client.logs(farm, unit, lines)
        except (RemoteError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"farm_id": farm.id, "unit": unit, "lines": output}

    return app


app = create_app() if os.environ.get("FARMHOUSE_SKIP_AUTO_APP") != "1" else FastAPI()
