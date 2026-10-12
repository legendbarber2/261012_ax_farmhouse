#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
ENABLE_NOW=0

usage() {
  cat <<'EOF'
사용법: scripts/install-controller.sh [--service-user USER] [--enable-now]

중앙 제어 API용 가상환경과 systemd 유닛을 설치합니다.
controller/config.json과 SSH 개인키는 자동 생성하지 않습니다.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --service-user) SERVICE_USER="$2"; shift 2 ;;
    --enable-now) ENABLE_NOW=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "${SERVICE_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || {
  echo "올바르지 않은 서비스 사용자입니다: ${SERVICE_USER}" >&2
  exit 2
}
id "${SERVICE_USER}" >/dev/null 2>&1 || {
  echo "서비스 사용자가 존재하지 않습니다: ${SERVICE_USER}" >&2
  exit 2
}
[[ -r "${PROJECT_ROOT}/controller/config.json" ]] || {
  echo "controller/config.example.json을 controller/config.json으로 복사하고 값을 확인하세요." >&2
  exit 1
}

echo "[1/3] Python 가상환경 설치"
if [[ ! -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  sudo -u "${SERVICE_USER}" python3 -m venv "${PROJECT_ROOT}/.venv"
fi
sudo -u "${SERVICE_USER}" "${PROJECT_ROOT}/.venv/bin/python" -m pip install \
  --disable-pip-version-check -r "${PROJECT_ROOT}/controller/requirements.txt"

echo "[2/3] systemd 유닛 생성"
SERVICE_GROUP="$(id -gn "${SERVICE_USER}")"
sed \
  -e "s|@SERVICE_USER@|${SERVICE_USER}|g" \
  -e "s|@SERVICE_GROUP@|${SERVICE_GROUP}|g" \
  -e "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" \
  "${PROJECT_ROOT}/controller/systemd/farmhouse-controller.service.in" \
  | sudo tee /etc/systemd/system/farmhouse-controller.service >/dev/null
sudo systemctl daemon-reload

echo "[3/3] 설치 확인"
sudo systemd-analyze verify /etc/systemd/system/farmhouse-controller.service
if (( ENABLE_NOW )); then
  sudo systemctl enable --now farmhouse-controller.service
  sudo systemctl --no-pager --full status farmhouse-controller.service
else
  echo "아직 활성화하지 않았습니다. 설정 확인 후 --enable-now로 다시 실행하세요."
fi

