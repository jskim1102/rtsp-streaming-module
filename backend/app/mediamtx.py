"""mediamtx path 동기화 — RTSP 카메라를 mediamtx API 로 등록/삭제/조회.

백엔드는 mediamtx 의 control plane 만 담당(가벼움) — 실제 스트리밍/transcode 는
mediamtx 컨테이너가 한다. v1 에서 떼냈던 경로를 v2 에서 복원한 모듈.
"""

import logging

import httpx
from sqlalchemy.orm import Session

from app.config import MEDIAMTX_API
from app.models import IpCam

logger = logging.getLogger("rtsp-streaming.mediamtx")


def _validate_rtsp_url(rtsp_url: str) -> None:
    """rtsp_url 트러스트 경계 검증 (injection 2중 방어의 1단 — spec v2-transcode-binding §영향).

    - 스킴은 `rtsp://` 또는 `rtsps://`(TLS) 만 허용.
    - 제어문자(\\n \\r \\x00) + 공백/탭 거부 — runOnDemand 가 셸 없이 mediamtx 가
      공백으로 arg 분리하므로, 공백/제어문자가 있으면 ffmpeg 인자가 깨진다.
    RFC1918/loopback IP 는 거부하지 않는다 — IP 카메라는 LAN(192.168.x)에 있는 게 정상.
    """
    if not (rtsp_url.startswith("rtsp://") or rtsp_url.startswith("rtsps://")):
        raise ValueError(f"rtsp:// 또는 rtsps:// 스킴이 아닙니다: {rtsp_url!r}")
    # 공백/제어문자 + 셸 메타문자 거부 (denylist). runOnDemand 는 셸 없이 직접 exec 되지만,
    # mediamtx 의 $ 변수치환 + 미래 셸-wrapping 대비 defense-in-depth.
    # allowlist 가 아닌 denylist — `!`/`@`/`%` 등 RTSP 비밀번호의 valid 문자는 허용해야 한다.
    _FORBIDDEN = ("\n", "\r", "\x00", " ", "\t",
                  "$", "`", ";", "|", "&", "(", ")", "{", "}", "<", ">", "\\", "'", '"')
    if any(c in rtsp_url for c in _FORBIDDEN):
        raise ValueError(f"rtsp_url 에 금지문자(공백/제어/셸메타)가 포함돼 있습니다: {rtsp_url!r}")


def _transcode_command(rtsp_url: str) -> str:
    """조건부 transcode runOnDemand bash 래퍼 (패턴 C, spec v2-transcode-binding).

    카메라 rtsp_url 은 등록 시점에 `shlex.quote` 로 치환되고(injection 가드),
    `$RTSP_PORT`/`$MTX_PATH` 는 literal 로 남아 mediamtx 가 런타임에 치환한다.
    ffprobe/ffmpeg 는 mediamtx 컨테이너 안에서 실행 → 백엔드 순수 Python.
    h264=passthrough(copy), 그 외(H.265/MJPEG 등)=libx264.
    """
    # mediamtx 는 runOnDemand 의 `$VAR` 를 자기 변수로 치환한다 → 셸 변수 `$C`/`$V` 가
    # 빈 문자열로 먹혀 조건분기가 깨진다(ffmpeg 가 -c:v 없이 mpeg4 기본 인코딩 → WebRTC 실패).
    # 그래서 셸/조건 없이 ffmpeg 를 직접, **항상 H.264** 로 transcode 한다(모든 코덱 호환).
    # H.264 소스도 재인코딩하는 비용은 있으나(passthrough 최적화 포기) 동작 보장이 우선.
    #
    # `-force_key_frames expr:gte(t,n_forced*2)` = 2초마다 출력 keyframe(IDR) 강제.
    # libx264 기본 keyint=250프레임은 fps 의존적이라 저fps 카메라(예: 2fps)는 keyframe
    # 간격이 125초까지 벌어져, WHEP 뷰어가 다음 IDR 까지 수십초 기다린다(연결 지연).
    # 시간기반 강제로 fps 무관하게 ~2초 내 join 보장. (공백/`$` 없어 mediamtx 치환 안전.)
    #
    # `$RTSP_PORT`/`$MTX_PATH` 는 mediamtx 변수 — 정상 치환된다. rtsp_url 은 검증됨(공백/제어문자/비-rtsp 거부).
    return (
        f"ffmpeg -rtsp_transport tcp -i {rtsp_url} "
        "-c:v libx264 -preset veryfast -tune zerolatency "
        "-force_key_frames expr:gte(t,n_forced*2) -an "
        "-f rtsp rtsp://localhost:$RTSP_PORT/$MTX_PATH"
    )


def _require_api() -> str:
    """MEDIAMTX_API 가 설정돼 있는지 확인 — 없으면 명시적 fail-fast.

    config 가 빈 문자열(미설정)이면 httpx 가 cryptic 'missing protocol' 에러를
    던지고 register/remove 는 그걸 silent 하게 삼킨다. 그 전에 명확히 막는다.
    """
    if not MEDIAMTX_API:
        raise RuntimeError(
            "MEDIAMTX_API 가 설정되지 않았습니다. "
            "Docker 는 compose environment 로, 로컬은 backend/.env 로 주입하세요."
        )
    return MEDIAMTX_API


def register_stream(stream_key: str, rtsp_url: str) -> bool:
    """mediamtx 에 path 등록 — 조건부 transcode runOnDemand (패턴 C).

    `{source: rtsp}` 패스스루 대신 runOnDemand 로 등록해 H.264 외 코덱을 재인코딩한다.
    rtsp_url 은 bash 에 들어가므로 검증 후 사용.
    """
    _require_api()
    _validate_rtsp_url(rtsp_url)
    try:
        resp = httpx.post(
            f"{MEDIAMTX_API}/v3/config/paths/add/{stream_key}",
            json={
                "runOnDemand": _transcode_command(rtsp_url),
                "runOnDemandCloseAfter": "10s",
            },
            timeout=5,
        )
        if resp.status_code in (200, 201):
            logger.info("mediamtx path 등록: %s → %s", stream_key, rtsp_url)
            return True
        logger.warning("mediamtx 등록 실패: %d %s", resp.status_code, resp.text)
        return False
    except httpx.HTTPError:
        logger.exception("mediamtx 연결 실패 (등록: %s)", stream_key)
        return False


def remove_stream(stream_key: str) -> None:
    """mediamtx 에서 스트림 path 제거"""
    _require_api()
    try:
        resp = httpx.delete(
            f"{MEDIAMTX_API}/v3/config/paths/delete/{stream_key}",
            timeout=5,
        )
        if resp.status_code in (200, 204):
            logger.info("mediamtx path 제거: %s", stream_key)
        else:
            logger.warning("mediamtx 제거 실패: %d %s", resp.status_code, resp.text)
    except httpx.HTTPError:
        logger.exception("mediamtx 연결 실패 (제거: %s)", stream_key)


def sync_streams(db: Session) -> None:
    """서버 시작 시 DB 의 모든 IP CAM 을 mediamtx 에 재등록"""
    cams = db.query(IpCam).all()
    for cam in cams:
        register_stream(cam.stream_key, cam.rtsp_url)
    logger.info("mediamtx 동기화 완료: %d개 스트림", len(cams))


def get_path(stream_key: str) -> dict | None:
    """mediamtx path 상태 조회 (/v3/paths/get/<path>).

    반환은 mediamtx 응답 dict (`ready`, `readers` 등) 또는 path 없으면 None.
    """
    _require_api()
    try:
        resp = httpx.get(f"{MEDIAMTX_API}/v3/paths/get/{stream_key}", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        return None
    except httpx.HTTPError:
        logger.exception("mediamtx path 조회 실패: %s", stream_key)
        return None
