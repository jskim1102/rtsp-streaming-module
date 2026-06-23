import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy.orm import Session

from app.config import MAX_IPCAMS
from app.database import get_db
from app.masking import _restore_masked_password, mask_rtsp_credentials
from app.mediamtx import get_path, register_stream, remove_stream
from app.mediamtx import _validate_rtsp_url
from app.models import IpCam

logger = logging.getLogger("rtsp-streaming.ipcam")

router = APIRouter(prefix="/api/ipcams", tags=["ipcam"])


def _check_rtsp_url(rtsp_url: str) -> None:
    """rtsp_url 검증 — 위험하면 400 (DB 쓰기 전에 막아 오염·500 방지)."""
    try:
        _validate_rtsp_url(rtsp_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _register_or_fail(stream_key: str, rtsp_url: str) -> bool:
    """register_stream 호출 — mediamtx 미설정(RuntimeError)·실패(False) 모두 False 로 정규화.

    호출부가 commit 전에 등록 성공을 확인하고, 실패 시 rollback 할 수 있게 한다(P1-3).
    """
    try:
        return register_stream(stream_key, rtsp_url)
    except RuntimeError:
        logger.exception("mediamtx 미설정으로 스트림 등록 불가: %s", stream_key)
        return False


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

    @field_serializer("rtsp_url")
    def _mask_url(self, v: str) -> str:
        # 모든 응답(list/create/update)에서 비밀번호 마스킹 — 평문 자격증명 노출 차단.
        return mask_rtsp_credentials(v)


# ─── 엔드포인트 ───


@router.get("", response_model=list[IpCamResponse])
def list_ipcams(db: Session = Depends(get_db)) -> list[IpCam]:
    """등록된 IP CAM 목록 조회"""
    return db.query(IpCam).order_by(IpCam.id).all()


@router.post("", response_model=IpCamResponse, status_code=201)
def create_ipcam(body: IpCamCreate, db: Session = Depends(get_db)) -> IpCam:
    """IP CAM 등록 + mediamtx path 등록. 등록 대수가 MAX_IPCAMS 이상이면 409."""
    _check_rtsp_url(body.rtsp_url)
    if db.query(IpCam).count() >= MAX_IPCAMS:
        raise HTTPException(
            status_code=409,
            detail=f"최대 {MAX_IPCAMS}대까지 등록할 수 있습니다",
        )

    cam = IpCam(name=body.name, rtsp_url=body.rtsp_url)
    db.add(cam)
    db.flush()  # commit 전에 INSERT → id/stream_key 확보 (mediamtx 등록 성공 확인 후 commit)

    if not _register_or_fail(cam.stream_key, cam.rtsp_url):
        # mediamtx 등록 실패 시 DB 도 롤백 — "성공처럼 보이는 실패" 방지(P1-3).
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="mediamtx 스트림 등록에 실패했습니다 — 카메라가 저장되지 않았습니다",
        )

    db.commit()
    db.refresh(cam)
    logger.info("IP CAM 등록: id=%d name=%s stream_key=%s", cam.id, cam.name, cam.stream_key)
    return cam


@router.put("/{cam_id}", response_model=IpCamResponse)
def update_ipcam(cam_id: int, body: IpCamUpdate, db: Session = Depends(get_db)) -> IpCam:
    """IP CAM 수정 + (rtsp 변경 시) mediamtx path 재등록.

    rtsp_url 의 비밀번호가 마스킹된 채로(`:***@`) 들어오면, *** 부분만 기존 실제 비밀번호로
    되돌리고 host/port/path 등 나머지 변경은 그대로 적용한다 — 비밀번호 재입력 없이 주소만
    바꿔도 반영된다. 비밀번호를 바꾸려면 *** 를 지우고 새 비밀번호를 입력한다.
    """
    cam = db.query(IpCam).filter(IpCam.id == cam_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="IP CAM을 찾을 수 없습니다")

    old_url = cam.rtsp_url
    # *** 마스킹된 비밀번호만 기존 실제값으로 복원, 나머지 수정(주소 등)은 보존.
    new_url = _restore_masked_password(body.rtsp_url, old_url)
    if new_url != old_url:
        _check_rtsp_url(new_url)

    cam.name = body.name
    cam.rtsp_url = new_url
    db.flush()

    # RTSP 주소가 변경된 경우에만 mediamtx path 재등록 (add 는 중복 거부 → remove 먼저).
    if new_url != old_url:
        remove_stream(cam.stream_key)
        if not _register_or_fail(cam.stream_key, new_url):
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail="mediamtx 재등록에 실패했습니다 — 변경이 저장되지 않았습니다",
            )

    db.commit()
    db.refresh(cam)
    logger.info("IP CAM 수정: id=%d name=%s", cam.id, cam.name)
    return cam


@router.delete("/{cam_id}", status_code=204)
def delete_ipcam(cam_id: int, db: Session = Depends(get_db)) -> None:
    """IP CAM 삭제 + mediamtx path 제거."""
    cam = db.query(IpCam).filter(IpCam.id == cam_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="IP CAM을 찾을 수 없습니다")

    remove_stream(cam.stream_key)

    db.delete(cam)
    db.commit()
    logger.info("IP CAM 삭제: id=%d stream_key=%s", cam_id, cam.stream_key)


@router.get("/{stream_key}/stats")
def get_ipcam_stats(stream_key: str) -> dict:
    """IP CAM path 활성/시청자수 (mediamtx /v3/paths/get 기반).

    - active: mediamtx path 가 ready (source 연결됨)
    - readers: 현재 WHEP 시청자 수
    path 가 없거나 ready 아니면 `{active: false, readers: 0}`.
    """
    path = get_path(stream_key)
    if not path or not path.get("ready"):
        return {"active": False, "readers": 0}
    return {"active": True, "readers": len(path.get("readers", []))}
