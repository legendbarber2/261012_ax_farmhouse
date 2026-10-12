from controller.app import create_app
from controller.remote import RemoteResult
from controller.settings import FarmSettings, SSHSettings, Settings
from fastapi.testclient import TestClient


class FakeRemote:
    def status(self, farm):
        return {
            "id": farm.id,
            "name": farm.name,
            "online": True,
            "ptz_enabled": False,
            "report": {"disk": {"free_bytes": 100}, "sessions": {"uploaded": 1}},
            "services": {"farm-camera-collect.service": "active"},
        }

    def list_images(self, farm, **kwargs):
        return {"total": 0, "items": []}

    def action(self, farm, action):
        return RemoteResult(stdout=f"{farm.id}:{action}", stderr="", returncode=0)

    def logs(self, farm, unit, lines):
        return "ok"


def settings():
    return Settings(
        allowed_users=(),
        cors_origins=("https://legendbarber2.github.io",),
        dev_auth=True,
        ssh=SSHSettings(identity_file="/tmp/test"),
        farms=(
            FarmSettings(
                id="ha",
                name="HA 농가",
                host="100.64.0.1",
                user="theimc-ha",
                project_dir="/home/theimc-ha/farm-camera",
            ),
        ),
    )


def test_dashboard_in_local_dev_mode():
    client = TestClient(create_app(settings(), FakeRemote()))
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["farms"][0]["online"] is True


def test_unknown_farm_is_404():
    client = TestClient(create_app(settings(), FakeRemote()))
    response = client.get("/api/farms/unknown/status")
    assert response.status_code == 404

