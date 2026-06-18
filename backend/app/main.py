from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS, logger
from app.database import init_db
from app.ipcam import router as ipcam_router
from app.streaming import manager as stream_manager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """서버 시작/종료 시 리소스 관리."""
    # alembic 이 스키마 정본이지만, 테스트/로컬 첫 실행 편의를 위해 init_db() 유지.
    init_db()

    # 캡처 매니저 기동
    stream_manager.startup()

    logger.info("RTSP Streaming API 서버 시작")
    yield
    logger.info("서버 종료 중 — 캡처 리소스 정리")
    stream_manager.shutdown()
    logger.info("서버 종료 완료")


app = FastAPI(title="RTSP Streaming API", lifespan=lifespan)

# CORS
cors_origins = ["*"] if CORS_ORIGINS == "*" else [o.strip() for o in CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ipcam_router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
