# AX Farmhouse Control

농가 5곳의 CCTV 이미지 수집 프로그램을 한 화면에서 점검하고 제한된 운영 작업을 실행하는 웹 제어판입니다.

## 구성

```text
GitHub Pages 정적 화면
        │ HTTPS (브라우저가 Tailnet에 연결된 경우에만 접근)
        ▼
Tailscale Serve → 127.0.0.1:8765 중앙 제어 API
        │ SSH (전용 키, 허용된 명령만 실행)
        ├── GH 농가 PC
        ├── GJ 농가 PC
        ├── GS 농가 PC
        ├── HA 농가 PC
        └── NW 농가 PC
```

- `web/`: GitHub Pages에 배포되는 정적 화면
- `controller/`: 하둡 서버에서 실행할 FastAPI 중앙 제어 API
- `scripts/install-controller.sh`: API systemd 서비스 설치
- `.github/workflows/pages.yml`: `main` 푸시 시 Pages 자동 배포

GitHub Pages에는 SSH 키, CCTV 계정, RTSP 주소를 넣지 않습니다. API는 `127.0.0.1`에만 바인딩하고 Tailscale Serve를 통해서만 공개합니다. Tailscale Serve는 Tailnet 요청자의 신원 헤더를 백엔드에 전달하며, API는 이 헤더로 접근자를 확인합니다.

## 현재 제공 기능

- 농가별 온라인 상태, 서비스 상태, 디스크 여유 공간, 세션 수
- CAM01~03 즉시 작물 촬영
- 완료 세션 HDFS 업로드 재시도
- 운영 점검과 수집 서비스 재시작
- 농가·카메라·촬영 종류별 저장 이미지 조회 및 다운로드
- 수집·작물 촬영·업로드 로그 조회
- PTZ 화면과 제한된 API 계약

PTZ 화면은 포함되어 있지만 농가 PC에 `scripts/control-camera-ptz.sh`를 설치하고 장치별 ONVIF 동작을 검증하기 전까지 `ptz_enabled=false`로 유지합니다. 정기 작물 촬영의 고정 화각을 보호하기 위해 홈 프리셋 복귀가 확인된 뒤 활성화합니다.

## 로컬 화면 확인

```bash
python3 -m http.server 8080 --directory web
```

브라우저에서 `http://127.0.0.1:8080`을 엽니다. 실제 API 연결 전에도 화면 배치를 확인할 수 있습니다.

## 중앙 제어 API 준비

하둡 서버에 이 저장소를 복제한 뒤 진행합니다.

```bash
cp controller/config.example.json controller/config.json
chmod 600 controller/config.json
```

`controller/config.json`에서 다음을 확인합니다.

- `allowed_users`: 접근을 허용할 실제 `Tailscale-User-Login`. 빈 배열이면 Tailnet에서 API에 접근할 수 있는 모든 사용자 허용
- `cors_origins`: GitHub Pages Origin인 `https://legendbarber2.github.io`
- `ssh.identity_file`: 중앙 제어 전용 SSH 개인키 절대 경로
- 농가별 Tailscale IP, 사용자, 프로젝트 경로
- `ptz_enabled`: 장치 제어 검증 전에는 반드시 `false`

중앙 제어 전용 키는 하둡 서버에서 새로 만듭니다.

```bash
sudo install -d -m 700 -o hadoop -g hadoop /var/lib/farmhouse-controller
sudo -u hadoop ssh-keygen -t ed25519 \
  -f /var/lib/farmhouse-controller/id_ed25519 \
  -C farmhouse-controller -N ''
```

공개키를 GH·GJ·GS·HA·NW 농가 PC의 `~/.ssh/authorized_keys`에 추가한 뒤 API를 설치합니다.

```bash
sudo scripts/install-controller.sh --service-user hadoop --enable-now
```

로컬 API 상태:

```bash
curl http://127.0.0.1:8765/api/health
```

직접 호출은 Tailscale 신원 헤더가 없으므로 `401`이 정상입니다.

## Tailscale Serve 연결

하둡 서버를 동일한 Tailnet에 연결하고 HTTPS를 활성화한 뒤 실행합니다.

```bash
sudo tailscale serve --bg 8765
tailscale serve status
```

출력된 `https://...ts.net` 주소를 웹 화면 오른쪽 위 연결 설정에 입력합니다. API는 공개 Funnel이 아니라 Tailnet 전용 Serve만 사용합니다.

## GitHub Pages 배포

저장소의 `Settings → Pages → Build and deployment`에서 Source를 `GitHub Actions`로 지정합니다. 이후 `main` 브랜치 푸시마다 `web/`이 배포됩니다.

```bash
git add .
git commit -m "Build farm camera operations dashboard"
git push -u origin main
```

배포 주소는 다음 형식입니다.

```text
https://legendbarber2.github.io/261012_ax_farmhouse/
```

## 테스트

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r controller/requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q controller/tests
```

## 보안 원칙

- 브라우저에서 임의 셸 명령을 전달할 수 없습니다.
- 농가 ID, 카메라 ID, 작업 종류는 서버의 허용 목록으로 검증합니다.
- 이미지 경로는 `data/farm_work`와 `data/crop` 아래 JPEG만 허용합니다.
- API는 localhost에만 바인딩하고 Tailscale Serve의 신원 헤더를 요구합니다.
- 수집 서비스 재시작은 농가 PC에 최소 범위의 비밀번호 없는 sudo 규칙이 있을 때만 성공합니다.
- 공개 저장소에 `controller/config.json`, SSH 개인키, CCTV 비밀번호를 커밋하지 않습니다.

참고 문서: [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve), [GitHub Pages 자동 배포](https://docs.github.com/en/get-started/start-your-journey/deploying-your-website-automatically)
