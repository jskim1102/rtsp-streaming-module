# rtsp-streaming

![rtsp-streaming 대시보드 — 카메라 CRUD + NxN 실시간 그리드](docs/dashboard.png)

웹서버에서 RTSP 카메라를 등록·수정·삭제하고, 서버(opencv/FFMPEG)가 모든 코덱을 디코딩해 **WS-JPEG 단일 경로**로 브라우저에 스트리밍하는 자기완결 모듈. NxN 자동 그리드 동시뷰 포함. 사용자는 코덱을 고를 필요 없이 웬만한 RTSP 코덱(H.264/H.265/MJPEG 등)이 자동 스트리밍된다.

**mediamtx·HLS·추론(YOLO/pose) 전부 비대상** — 다른 프로젝트가 `ipcam_router` 를 include 해서 갖다쓰는 라이브러리.

---

# 로컬 실행

backend(FastAPI, venv) + frontend(React/Vite) 를 직접 구동. mediamtx 없이 카메라 등록·스트리밍·라이브뷰까지 동작.

```bash
# 1. clone
git clone <repo-URL> rtsp-streaming
cd rtsp-streaming

# 2. 환경변수 (backend 가 .env 읽음 — 없으면 기본값으로 동작)
cp backend/.env.example backend/.env

# 3. 백엔드 (venv + alembic 스키마 + uvicorn)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head            # ip_cams 테이블 생성 (스키마 = migration 정본)
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8004

# 4. 프론트엔드 (새 터미널)
cd ../frontend
npm install
npm run dev -- --port 5177                # → http://localhost:5177
```

> 프론트는 브라우저에서 백엔드(`http://<host>:8004`)를 **직접** 호출한다. 로컬은 두 포트 다 localhost 라 그대로 동작.

---

# Docker (전체 스택)

backend + frontend 2컨테이너를 한 번에 기동. backend 컨테이너는 entrypoint 가 `alembic upgrade head` 로 스키마를 적용한 뒤 uvicorn 을 띄운다.

```bash
# 1. clone
git clone <repo-URL> rtsp-streaming
cd rtsp-streaming

# 2. 포트 설정 (compose 가 .env 읽음 — placeholder 라 값 채워야 함)
cp .env.example .env
#   .env 편집: PORT_OFFSET / BACKEND_PORT / FRONTEND_PORT 설정 (예: 4 / 8004 / 5177)

# 3. 빌드 + 기동
docker compose up -d --build
# → frontend http://localhost:5177 · backend :8004
```

종료: `docker compose down`

> ⚠️ **스키마/migration 을 바꾼 뒤 재빌드**할 땐 `docker compose down -v` 로 named volume(`ipcam_db`)을 리셋해야 한다. `-v` 없이 내리면 옛 `alembic_version` 이 남아 새 entrypoint 의 `alembic upgrade head` 가 "Can't locate revision" 으로 실패 → backend restart loop.

---

## 포트

| 서비스 | 포트 |
|---|---|
| Frontend | 5177 (컨테이너 80) |
| Backend (FastAPI · REST + WS) | 8004 (컨테이너 8000) |

포트는 `.env` 의 `${BACKEND_PORT}` / `${FRONTEND_PORT}` 로 참조된다(하드코딩 X). 실제 값은 `.env` 에만(gitignore), `.env.example` 에 placeholder.

---

## ⚠️ 접속 / 방화벽 (실사용 주의)

브라우저가 **프론트(정적)와 백엔드(REST+WS)를 직접** 호출한다(프록시 없음). 따라서 **두 포트 모두** 외부에서 닿아야 한다:

```bash
sudo ufw allow 5177   # frontend
sudo ufw allow 8004   # backend (API + WS)
```

외부(공인 IP/도메인)에서 접속하려면 라우터 포트포워딩도 **두 포트 다**. 백엔드(8004) 포워딩을 빠뜨리면 프론트는 떠도 카메라 등록/스트리밍이 동작하지 않는다(브라우저→백엔드 호출이 막힘).

---