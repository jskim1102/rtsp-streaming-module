import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_serializer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import MAX_IPCAMS
from app.database import get_db
from app.masking import _MASK, _restore_masked_password, _split_credentials, mask_rtsp_credentials
from app.mediamtx import ensure_stream, register_stream, remove_stream, update_stream
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


def _update_or_fail(stream_key: str, rtsp_url: str) -> bool:
    """update_stream(PATCH) 호출 — 미설정(RuntimeError)·실패(False) 모두 False 로 정규화.

    update 의 암전방지 롤백순서용: 호출부가 commit 전에 PATCH 성공을 확인하고, 실패 시
    DB rollback 한다. PATCH 실패면 mediamtx 가 기존 path 를 보존하므로 카메라 암전이 없다.
    """
    try:
        return update_stream(stream_key, rtsp_url)
    except RuntimeError:
        logger.exception("mediamtx 미설정으로 스트림 갱신 불가: %s", stream_key)
        return False


def _remove_or_fail(stream_key: str) -> bool:
    """remove_stream 호출 — 미설정(RuntimeError)·실패(False) 모두 False 로 정규화.

    호출부(delete_ipcam)가 commit 전에 mediamtx path 제거 성공(또는 이미 없음=멱등)을 확인하고,
    실패 시 DB row 삭제를 중단한다 — 삭제된 카메라의 mediamtx path 가 살아남아 URL 로 계속
    재생되는 orphan 라이브 스트림(노출면 격리 붕괴)을 막는다(codex #4, security).
    """
    try:
        return remove_stream(stream_key)
    except RuntimeError:
        logger.exception("mediamtx 미설정으로 스트림 제거 불가: %s", stream_key)
        return False


def _guard_masked_credential_exfil(new_raw: str, old_url: str) -> None:
    """비번 마스킹복원(***) credential-exfil 가드 (security HIGH).

    update 시 비밀번호가 `***`(마스킹) 채로 들어오면 기존 실제 비번이 복원돼 등록된다.
    이때 비번 외 컴포넌트(scheme/user/host/port/path)가 바뀌어 있으면, 사용자가 모르는
    **다른 호스트로 실제 비번이 재전송**될 수 있다(예: `:***@공격자host`). 이를 막기 위해
    비번이 *** 이면서 나머지가 old 와 다르면 거부 — 평문 비번 재제출을 요구한다.
    비번이 *** 가 아니거나(사용자가 새 비번 입력) old 에 자격증명이 없으면 가드 무관.
    """
    new = _split_credentials(new_raw)
    if new is None or new[2] != _MASK:
        return  # 자격증명 없음 / 비번이 *** 아님 (사용자가 새 비번 전체 입력) — 복원 안 일어남
    old = _split_credentials(old_url)
    # old 에 복원할 실제 비번이 없으면 복원할 게 없음 — 가드 무관(_restore 가 그대로 통과).
    if old is None or old[2] is None:
        return
    # new[2](비번)만 빼고 prefix(scheme)·user·rest(host:port/path) 가 동일해야 복원 허용.
    if (new[0], new[1], new[3]) != (old[0], old[1], old[3]):
        raise HTTPException(
            status_code=400,
            detail="비밀번호를 *** 그대로 두고 주소(호스트/경로 등)를 바꿀 수 없습니다 — "
                   "주소를 변경하려면 실제 비밀번호를 다시 입력하세요.",
        )


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
    # F7 동시성: count+insert 를 SQLite 쓰기 락으로 직렬화한다. count 조회 *전에* BEGIN IMMEDIATE
    # 로 RESERVED 락을 먼저 획득 — 동시에 들어온 다른 생성 요청은 이 트랜잭션이 commit 될 때까지
    # (busy_timeout 만큼) 대기했다가 갱신된 count 를 다시 관찰한다. 이렇게 하지 않으면 두 요청이
    # 모두 count<MAX 를 보고 둘 다 insert 해 cap 을 초과할 수 있다(SQLite 의 count SELECT 는
    # autocommit 이라 락을 잡지 않으므로 락을 명시적으로 선점해야 한다).
    db.execute(text("BEGIN IMMEDIATE"))
    if db.query(IpCam).count() >= MAX_IPCAMS:
        db.rollback()  # 위에서 선점한 쓰기 락 해제 후 409
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
    """IP CAM 수정 + (rtsp 변경 시) mediamtx path PATCH 갱신.

    rtsp_url 의 비밀번호가 마스킹(`:***@`)이고 **주소(scheme/user/host/port/path)가 기존과 동일**
    하면, *** 를 기존 실제 비밀번호로 복원해 저장한다(비번 재입력 없이 이름 등만 수정하는 경우).
    비밀번호가 *** 인 채로 **주소를 바꾸면 거부한다(400)** — 실비번이 사용자가 모르는 호스트로
    재전송되는 credential-exfil 을 막기 위해, 주소 변경 시엔 실제 비밀번호를 다시 입력해야 한다
    (_guard_masked_credential_exfil). 비밀번호 자체를 바꿀 때도 *** 를 지우고 새 비밀번호를 입력한다.
    """
    cam = db.query(IpCam).filter(IpCam.id == cam_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="IP CAM을 찾을 수 없습니다")

    old_url = cam.rtsp_url
    # 보안: 비번이 *** 인 채로 주소(host 등)만 바꾸면 실비번이 다른 호스트로 샐 수 있다 —
    # 비번 외 컴포넌트가 바뀌었으면 400(평문 재입력 요구). 동일할 때만 복원 허용.
    _guard_masked_credential_exfil(body.rtsp_url, old_url)
    # *** 마스킹된 비밀번호만 기존 실제값으로 복원, 나머지 수정(주소 등)은 보존.
    new_url = _restore_masked_password(body.rtsp_url, old_url)
    if new_url != old_url:
        _check_rtsp_url(new_url)

    cam.name = body.name
    cam.rtsp_url = new_url
    db.flush()

    # RTSP 주소 변경 시에만 mediamtx 갱신. update_stream(PATCH)이 새 url 을 기존 path 에
    # **원자적 부분 갱신**한다 — teardown-before-register(remove 선행) 없음. 성공 시 path 가
    # 새 url 로 그 자리에서 바뀌고, 실패 시 mediamtx 가 기존 config 를 그대로 보존하므로 old
    # path 가 살아있다(카메라 암전 0). 실패면 DB 도 롤백 → 503.
    if new_url != old_url:
        if not _update_or_fail(cam.stream_key, new_url):
            db.rollback()
            raise HTTPException(
                status_code=503,
                detail="mediamtx 재등록에 실패했습니다 — 변경이 저장되지 않았습니다(기존 스트림 유지)",
            )

    db.commit()
    db.refresh(cam)
    logger.info("IP CAM 수정: id=%d name=%s", cam.id, cam.name)
    return cam


@router.delete("/{cam_id}", status_code=204)
def delete_ipcam(cam_id: int, db: Session = Depends(get_db)) -> None:
    """IP CAM 삭제 + mediamtx path 제거.

    mediamtx path 제거가 실패하면 DB row 를 지우지 않는다(503) — 지우면 mediamtx path 가
    살아남아 삭제된 카메라가 URL 로 계속 재생되는 orphan 라이브 스트림(노출면 격리 붕괴)이
    된다(codex #4, security). 제거 성공(또는 이미 없음=멱등) 확인 후에만 commit.

    순서 = [mediamtx 제거 성공확인 → DB commit → sweep remove_stream]. commit 직후 sweep 으로
    remove_stream 을 한 번 더 호출한다 — 첫 제거~commit 사이에 stats 폴링의 ensure_stream
    (self-heal)이 path 를 재등록(resurrection)했을 수 있는데, 이 sweep 가 그 path 를 제거하고
    row 가 이미 없으니 ensure_stream 이 다시 재부활시키지 않는다(TOCTOU race 차단). sweep 은
    best-effort — commit 이 이미 끝났으므로 sweep 실패는 DB 일관성에 영향 없고 경고만 남긴다.
    """
    cam = db.query(IpCam).filter(IpCam.id == cam_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="IP CAM을 찾을 수 없습니다")

    stream_key = cam.stream_key  # commit 후 attribute expire 대비 — 미리 캡처

    if not _remove_or_fail(stream_key):
        raise HTTPException(
            status_code=503,
            detail="mediamtx 스트림 제거에 실패했습니다 — 카메라가 삭제되지 않았습니다",
        )

    db.delete(cam)
    db.commit()

    # row 가 사라진 뒤(=ensure_stream 이 더는 재등록 안 함) sweep 으로 race resurrection 제거.
    if not _remove_or_fail(stream_key):
        logger.warning("삭제 sweep 실패 — orphan path 가능성: stream_key=%s", stream_key)

    logger.info("IP CAM 삭제: id=%d stream_key=%s", cam_id, stream_key)


@router.get("/{stream_key}/stats")
def get_ipcam_stats(stream_key: str, db: Session = Depends(get_db)) -> dict:
    """IP CAM path 활성/시청자수 (mediamtx /v3/paths/get 기반).

    - active: mediamtx path 가 ready (source 연결됨)
    - readers: 현재 WHEP 시청자 수
    path 가 없거나 ready 아니면 `{active: false, readers: 0}`.

    self-heal: mediamtx 가 독립 재시작돼 path 가 사라졌으면 여기서 ensure_stream 이 자가복구
    재등록한다(register_stream idempotent). 프론트가 이 엔드포인트를 폴링하므로 mediamtx
    재시작 후 backend 재시작 없이 ~폴링주기 내 path 가 복원된다.

    ensure_stream 이 이미 조회한 path 를 그대로 반환받아 재사용한다 — 별도 get_path 재호출을
    없애 폴당 mediamtx httpx 를 2N→N 으로 줄인다(N=등록 카메라 수).
    """
    path = ensure_stream(db, stream_key)
    if not path or not path.get("ready"):
        return {"active": False, "readers": 0}
    return {"active": True, "readers": len(path.get("readers", []))}
