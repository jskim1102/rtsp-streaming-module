# syntax=docker/dockerfile:1.7
# rtsp-streaming backend — FastAPI + OpenCV(FFMPEG) RTSP 디코딩 + WS-JPEG.
# 베이스: python:3.11-slim (Debian slim), Linux 전용.
# 의존성: pip + requirements.txt. 추론(torch/ultralytics/CUDA)·mediamtx 비대상.

FROM python:3.11-slim

# -----------------------------------------------------------------------------
# 시스템 패키지
#   - libglib2.0-0 : opencv-python-headless 런타임 의존 (GLib)
#   - ffmpeg       : ffprobe 로 등록 시점 카메라 코덱 감지 (h264=passthrough/else=libx264 결정)
#   (torch 의 libgomp1, usbutils 는 비대상 — 추론/USB 웹캠 제거)
# -----------------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# -----------------------------------------------------------------------------
# 의존성 설치 (레이어 캐시 극대화)
#   opencv-python-headless 만 설치하므로 X11 의존 opencv-python 덮어쓰기
#   문제가 없다 → 강제 재설치 정리 블록 불필요.
# -----------------------------------------------------------------------------
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 애플리케이션 소스 + 마이그레이션 (alembic 이 스키마 정본 — RULES §9)
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

# 기동 시 alembic upgrade head 로 스키마 적용 후 uvicorn (init_db create_all 아님).
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
