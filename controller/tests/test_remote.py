import pytest

from controller.remote import SSHFarmClient, decode_image_id, encode_image_id, validate_image_path
from controller.settings import FarmSettings, SSHSettings


def test_image_id_round_trip():
    path = "data/crop/ha/2026/10/12/session/CAM01/images/example.jpg"
    assert decode_image_id(encode_image_id(path)) == path


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd.jpg",
        "data/crop/../../secret.jpg",
        "config/camera.jpg",
        "data/crop/image.png",
    ],
)
def test_image_path_rejects_unsafe_values(path):
    with pytest.raises(ValueError):
        validate_image_path(path)


def test_preview_rejects_unknown_camera():
    client = SSHFarmClient(SSHSettings(identity_file="/tmp/test"))
    farm = FarmSettings(
        id="ha",
        name="HA 농가",
        host="100.64.0.1",
        user="theimc-ha",
        project_dir="/home/theimc-ha/farm-camera",
    )
    with pytest.raises(ValueError):
        client.preview(farm, "CAM99")
