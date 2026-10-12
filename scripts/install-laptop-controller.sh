#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
SERVICE_FILE="${SERVICE_DIR}/farmhouse-controller.service"
ENABLE_NOW=0

usage() {
  cat <<'EOF'
사용법: scripts/install-laptop-controller.sh [--enable-now]

현재 사용자의 작업 노트북에 제어 API를 user systemd 서비스로 설치합니다.
sudo 권한과 하둡 서버 변경은 필요하지 않습니다.
EOF
}

while (($#)); do
  case "$1" in
    --enable-now) ENABLE_NOW=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ -r "${PROJECT_ROOT}/controller/config.json" ]] || {
  echo "controller/config.json이 없습니다." >&2
  exit 1
}
command -v python3 >/dev/null || {
  echo "python3가 필요합니다." >&2
  exit 1
}
command -v systemctl >/dev/null || {
  echo "systemctl이 필요합니다." >&2
  exit 1
}

echo "[1/3] Python 환경 준비"
if [[ ! -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  python3 -m venv "${PROJECT_ROOT}/.venv"
fi
"${PROJECT_ROOT}/.venv/bin/python" -m pip install \
  --disable-pip-version-check -r "${PROJECT_ROOT}/controller/requirements.txt"

echo "[2/3] user systemd 유닛 설치"
mkdir -p "${SERVICE_DIR}"
sed -e "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" \
  "${PROJECT_ROOT}/controller/systemd/farmhouse-controller-user.service.in" \
  > "${SERVICE_FILE}"
systemctl --user daemon-reload

echo "[3/3] 설치 확인"
systemd-analyze --user verify "${SERVICE_FILE}"
if (( ENABLE_NOW )); then
  systemctl --user enable --now farmhouse-controller.service
  systemctl --user --no-pager --full status farmhouse-controller.service
else
  echo "아직 활성화하지 않았습니다. --enable-now로 다시 실행하세요."
fi
