import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import CAPTURE_INTERVAL, MAX_IPCAMS
from app.database import get_db
from app.models import IpCam
from app.streaming import manager as stream_manager

logger = logging.getLogger("rtsp-streaming.ipcam")

router = APIRouter(prefix="/api/ipcams", tags=["ipcam"])


def _source_id(stream_key: str) -> str:
    """ipcam-<stream_key> 형식의 source_id."""
    return f"ipcam-{stream_key}"


# ─── 요청/응답 스키마 ───


class IpCamCreate(BaseModel):
    name: str
    rtsp_url: str


class IpCamUpdate(BaseModel):
    name: str
    rtsp_url: str


class IpCamResponse(BaseModel):
    id: int
    name: str
    rtsp_url: str
    stream_key: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── 엔드포인트 ───


@router.get("", response_model=list[IpCamResponse])
def list_ipcams(db: Session = Depends(get_db)) -> list[IpCam]:
    """등록된 IP CAM 목록 조회"""
    return db.query(IpCam).order_by(IpCam.id).all()


@router.post("", response_model=IpCamResponse, status_code=201)
def create_ipcam(body: IpCamCreate, db: Session = Depends(get_db)) -> IpCam:
    """IP CAM 등록 (DB-only). 등록 대수가 MAX_IPCAMS 이상이면 409."""
    if db.query(IpCam).count() >= MAX_IPCAMS:
        raise HTTPException(
            status_code=409,
            detail=f"최대 {MAX_IPCAMS}대까지 등록할 수 있습니다",
        )

    cam = IpCam(name=body.name, rtsp_url=body.rtsp_url)
    db.add(cam)
    db.commit()
    db.refresh(cam)

    logger.info("IP CAM 등록: id=%d name=%s stream_key=%s", cam.id, cam.name, cam.stream_key)
    return cam


@router.put("/{cam_id}", response_model=IpCamResponse)
def update_ipcam(cam_id: int, body: IpCamUpdate, db: Session = Depends(get_db)) -> IpCam:
    """IP CAM 수정"""
    cam = db.query(IpCam).filter(IpCam.id == cam_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="IP CAM을 찾을 수 없습니다")

    cam.name = body.name
    cam.rtsp_url = body.rtsp_url
    db.commit()
    db.refresh(cam)

    logger.info("IP CAM 수정: id=%d name=%s", cam.id, cam.name)
    return cam


@router.delete("/{cam_id}", status_code=204)
def delete_ipcam(cam_id: int, db: Session = Depends(get_db)) -> None:
    """IP CAM 삭제"""
    cam = db.query(IpCam).filter(IpCam.id == cam_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="IP CAM을 찾을 수 없습니다")

    # 진행 중 캡처 강제 종료
    sid = _source_id(cam.stream_key)
    stream_manager.stop_capture(sid)

    db.delete(cam)
    db.commit()
    logger.info("IP CAM 삭제: id=%d stream_key=%s", cam_id, cam.stream_key)


@router.get("/{stream_key}/stats")
def get_ipcam_stats(stream_key: str) -> dict:
    """IP CAM 의 source fps. 캡처 미동작 중이면 active=False."""
    sid = _source_id(stream_key)
    stats = stream_manager.get_capture_stats(sid)
    if stats is None:
        return {"active": False, "source_fps": 0.0}
    return {"active": True, **stats}


@router.websocket("/{stream_key}/ws")
async def ipcam_ws(websocket: WebSocket, stream_key: str) -> None:
    """RTSP 직접 캡처 → JPEG 프레임 WebSocket 송출 (binary only).

    DB 의 stream_key 로 IP CAM 조회 → rtsp_url 로 backend 가 직접 캡처.
    """
    # DB 에서 stream_key 로 cam 조회 (Depends 사용 못 해서 manual)
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        cam = db.query(IpCam).filter(IpCam.stream_key == stream_key).first()
    finally:
        db.close()

    if not cam:
        await websocket.close(code=1008, reason="등록되지 않은 stream_key")
        return

    await websocket.accept()
    sid = _source_id(stream_key)
    logger.info("WebSocket 연결: %s (rtsp=%s)", sid, cam.rtsp_url)

    if not stream_manager.start_capture(sid, cam.rtsp_url):
        logger.warning("Capture %s 시작 실패 — RTSP 연결 안 됨", sid)
        await websocket.close(code=1011, reason="RTSP 연결 실패")
        return

    try:
        # 첫 프레임 대기 (RTSP 는 연결 latency 있을 수 있어 longer)
        for _ in range(50):  # 최대 5초
            if stream_manager.get_frame(sid):
                break
            await asyncio.sleep(0.1)

        prev_frame: bytes = b""
        while True:
            # raw JPEG (binary frame)
            frame = stream_manager.get_frame(sid)
            if frame and frame is not prev_frame:
                await websocket.send_bytes(frame)
                prev_frame = frame

            await asyncio.sleep(CAPTURE_INTERVAL)
    except WebSocketDisconnect:
        logger.info("WebSocket 연결 해제: %s", sid)
    except Exception:
        logger.exception("WebSocket %s 전송 중 예외", sid)
    finally:
        stream_manager.stop_capture(sid)
