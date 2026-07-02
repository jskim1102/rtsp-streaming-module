# rtsp-streaming

![rtsp-streaming 대시보드 — 카메라 CRUD + NxN 실시간 그리드](docs/dashboard.png)

RTSP 카메라를 등록·수정·삭제하고, MediaMTX가 모든 코덱(H.264/H.265/MJPEG 등)을 H.264로 transcode해 브라우저에 WebRTC(WHEP)로 실시간 스트리밍하는 자기완결 모듈. NxN 자동 그리드(1줄 최대 4칸) 동시뷰 포함. 백엔드(FastAPI)는 카메라 CRUD + MediaMTX 제어만 담당 — 영상 디코딩은 안 거쳐 부하가 가볍다.

---

# 로컬 실행

backend(FastAPI) + frontend(React/Vite)를 `./dev.sh` 로 네이티브 구동한다. dev.sh 가
루트 `.env` 를 source 해 포트·공유 mediamtx 자격증명·VITE viewer 자격증명을 모두 주입하고,
backend(alembic upgrade → uvicorn) + frontend(vite) 를 함께 올린다(mediamtx 는 공유 인스턴스).

```bash
# 1. clone
git clone <repo-URL> rtsp-streaming
cd rtsp-streaming

# 2. 환경변수 (루트 .env — dev.sh 가 source, Docker 와 동일 파일)
cp .env.example .env
#   포트(PORT_OFFSET/BACKEND_PORT/FRONTEND_PORT) + 공유 mediamtx 접속값
#   (MEDIAMTX_API · MEDIAMTX_PATH_PREFIX · backend/viewer 자격증명)을
#   `harness mtx env rtsp-streaming` 출력으로 채운다. 미설정 시 무인증 접속·
#   UNPREFIXED stream_key 로 공유 인스턴스 path 격리가 깨진다.

# 3. 1회 셋업 (dev.sh 가 기대하는 사전조건: backend venv + frontend deps)
(cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)
(cd frontend && npm install)

# 4. 기동 (backend alembic+uvicorn + frontend vite 네이티브)
./dev.sh up      # 종료: ./dev.sh down
# → frontend :5177 · backend :8004 · 공유 MediaMTX WHEP :8889
```

> dev.sh 없이 수동으로 네이티브 구동하려면 루트 `.env` 를 source 하거나
> `harness mtx env rtsp-streaming` 출력을 export 해야 한다 — MEDIAMTX_PATH_PREFIX,
> backend 자격증명(MEDIAMTX_BACKEND_USER/PASS), VITE viewer 자격증명
> (VITE_MEDIAMTX_VIEWER_USER/PASS) 없이는 무인증 접속·UNPREFIXED 키로 path 격리가 깨진다.

> 영상 재생·카메라 등록은 **공유 MediaMTX(`harness-shared-mediamtx`)가 떠 있어야** 동작(브라우저가 MediaMTX에 직접 붙고, 등록도 MediaMTX 성공 확인 후 커밋). 전체 스택은 Docker 권장.

---

# Docker

backend + frontend **2컨테이너**를 기동한다. MediaMTX 는 이 repo 가 띄우지 않는다 — 여러 모듈이 공유하는 **공유 인스턴스(`harness-shared-mediamtx`)**에 입주하며, infra 가 미리 띄워 둔 외부 네트워크(`harness-shared-mtx`)에 backend 가 붙는다.

```bash
# 1. clone
git clone <repo-URL> rtsp-streaming
cd rtsp-streaming

# 2. 환경변수 (compose가 .env 읽음 — placeholder라 값 채워야 함)
cp .env.example .env
#   포트: PORT_OFFSET / BACKEND_PORT / FRONTEND_PORT / MEDIAMTX_WEBRTC_HOST
#   공유 mediamtx 접속값(MEDIAMTX_API · 자격증명 등)은 `harness mtx env rtsp-streaming` 출력으로 채운다.

# 3. 빌드 + 기동 (공유 mediamtx 인스턴스·네트워크가 떠 있어야 함)
docker compose up -d --build
# → frontend http://localhost:5177 · backend :8004 · 공유 MediaMTX WHEP :8889
```

종료: `docker compose down` (공유 mediamtx 는 건드리지 않는다)

> 외부에서 영상이 안 뜨면 `.env`의 `MEDIAMTX_WEBRTC_HOST`에 브라우저가 닿을 IP를 넣어라(LAN·공인, 쉼표구분). 미설정 시 MediaMTX가 컨테이너 내부 IP만 광고해 WebRTC 연결 실패.

---

## 포트

이 repo 가 직접 노출하는 포트는 frontend·backend 둘뿐이다. MediaMTX 포트는 **공유 인스턴스(infra 관리)** 소속이라 여기서 띄우지 않는다 — 실제 값은 `harness mtx env rtsp-streaming` 으로 확인.

| 서비스 | 포트 |
|---|---|
| Frontend | 5177 |
| Backend (FastAPI) | 8004 |
| 공유 MediaMTX WebRTC (영상, 브라우저 직접 접속) | 8889 |

외부 접속 시 방화벽·포트포워딩:

```bash
sudo ufw allow 5177/tcp    # frontend
sudo ufw allow 8004/tcp    # backend
sudo ufw allow 8889/tcp    # 공유 MediaMTX WebRTC (영상)
# + 공유 MediaMTX ICE(udp) 포트 — infra 의 공유 인스턴스 포트 배정에 따름(harness mtx env 로 확인)
```

> 인증 없음 — `:8004`에 닿는 누구나 CRUD 가능. rtsp 비밀번호는 응답에서 `***`로 마스킹된다. 공개 배포 시 리버스 프록시/인증 뒤에 둘 것.
