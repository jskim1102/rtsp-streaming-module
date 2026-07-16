# rtsp-streaming

![rtsp-streaming 대시보드 — 카메라 CRUD + NxN 실시간 그리드](docs/dashboard.png)

RTSP 카메라를 등록·수정·삭제하고, MediaMTX가 모든 코덱(H.264/H.265/MJPEG 등)을 H.264로 transcode해 브라우저에 WebRTC(WHEP)로 실시간 스트리밍하는 자립형 모듈. NxN 자동 그리드(1줄 최대 4칸) 동시뷰 포함. 백엔드(FastAPI)는 카메라 CRUD + MediaMTX 제어만 담당하고 영상 디코딩은 안 거쳐 부하가 가볍다.

`docker compose` 한 번으로 **backend + frontend + MediaMTX 세 컨테이너**가 함께 뜬다. 별도 인프라나 외부 스트리밍 서버가 필요 없다.

---

# 빠른 시작 (Docker)

카메라와 같은 LAN에 있는 PC에서 실행한다(서버가 카메라의 RTSP 주소에 직접 닿아야 하므로).

```bash
# 1. clone
git clone <repo-URL> rtsp-streaming
cd rtsp-streaming

# 2. 환경변수 파일 만들기
cp .env.example .env
#    .env 를 열어 빈 칸을 직접 채운다 (아래 "환경변수" 표 참고).
#    최소한 채워야 하는 값: BACKEND_PORT, FRONTEND_PORT,
#    MEDIAMTX_BACKEND_PASS, MEDIAMTX_VIEWER_PASS, MEDIAMTX_WEBRTC_HOST

# 3. 빌드 + 기동
docker compose up -d --build

# 종료: docker compose down   (다시 켜도 등록한 카메라는 유지됨)
```

브라우저에서 `http://<이_PC의_IP>:<FRONTEND_PORT>` 로 접속한다.

---

# 환경변수 (`.env`)

`.env.example` 을 복사해서 채운다. 비밀번호가 들어가므로 이 파일은 공유하지 않는다.

| 변수 | 필수 | 설명 |
|---|---|---|
| `BACKEND_PORT` | ✅ | 백엔드 API 포트 (예: `8004`). 브라우저가 이 포트로 직접 접속한다. |
| `FRONTEND_PORT` | ✅ | 웹페이지 포트 (예: `5177`). 브라우저 접속 주소. |
| `MEDIAMTX_BACKEND_PASS` | ✅ | MediaMTX 제어용 비밀번호. 직접 정한다. |
| `MEDIAMTX_VIEWER_PASS` | ✅ | 영상 시청용 비밀번호. 위와 **다른** 값으로 정한다. |
| `MEDIAMTX_WEBRTC_HOST` | 권장 | 이 PC의 LAN IP (예: `192.168.0.20`). **비우면 이 PC에서만 영상이 보이고 다른 기기에서는 화면이 검게 나온다.** 찾는 법: `hostname -I` (Linux/macOS) · `ipconfig` (Windows). |
| `MAX_IPCAMS` | 선택 | 등록 가능 카메라 수 (기본 16). |
| `CORS_ORIGINS` | 선택 | 허용할 접속 origin. 비우면 전체 허용. 공개 배포 시 프론트 주소로 한정 권장. |

나머지 값(`MEDIAMTX_API`, `MEDIAMTX_PATH_PREFIX`, `MEDIAMTX_WEBRTC_PORT`, 사용자명)은 기본값이 들어 있어 단일 PC 설치에서는 그대로 둔다.

> **비밀번호 문자 제한**: MediaMTX가 비밀번호에 `%`, `?`, `/`, `:`, `,`, 공백, 따옴표 등을 허용하지 않는다. 영문·숫자와 `!@#-_.` 정도로만 정한다. 허용 안 되는 문자를 쓰면 MediaMTX 컨테이너가 계속 재시작한다.

---

# 포트 · 방화벽

기본 포트(`.env`에서 바꿀 수 있는 것은 표시).

| 서비스 | 포트 | 용도 |
|---|---|---|
| Frontend | `FRONTEND_PORT` (예 5177/tcp) | 웹페이지 |
| Backend (FastAPI) | `BACKEND_PORT` (예 8004/tcp) | API — 브라우저가 직접 호출 |
| MediaMTX WebRTC | 8889/tcp | 영상 연결 시작 |
| MediaMTX ICE | 8189/udp | **영상 데이터 — 없으면 영상이 안 나온다** |

다른 기기에서 접속하려면 방화벽/공유기에서 위 4개를 연다:

```bash
sudo ufw allow 5177/tcp    # frontend (FRONTEND_PORT 에 맞게)
sudo ufw allow 8004/tcp    # backend  (BACKEND_PORT 에 맞게)
sudo ufw allow 8889/tcp    # MediaMTX WebRTC (영상 연결)
sudo ufw allow 8189/udp    # MediaMTX ICE (영상 데이터 — 필수)
```

> 8189/udp를 빠뜨리면 카메라 화면이 "연결됨"까지 갔다가 영상만 안 뜨는, 원인 찾기 어려운 증상이 난다. 반드시 연다.

---

# 주의

- **인증 없음** — `BACKEND_PORT`에 닿는 누구나 카메라 CRUD가 가능하다. rtsp 비밀번호는 응답에서 `***`로 마스킹된다. 공개 배포 시 리버스 프록시/인증 뒤에 둔다.
- 카메라 등록은 MediaMTX 등록이 성공해야 저장된다. MediaMTX가 준비되기 전 잠깐은 등록이 실패할 수 있으나 곧 정상화된다.
