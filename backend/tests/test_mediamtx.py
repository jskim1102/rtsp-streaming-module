"""mediamtx 모듈 테스트 — fail-fast(MEDIAMTX_API 미설정) + runOnDemand transcode
payload + rtsp_url injection 가드.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

import app.mediamtx as mediamtx


def test_register_stream_raises_when_api_unset():
    with patch.object(mediamtx, "MEDIAMTX_API", ""):
        with pytest.raises(RuntimeError, match="MEDIAMTX_API"):
            mediamtx.register_stream("ipcam-x", "rtsp://x/1")


def test_remove_stream_raises_when_api_unset():
    with patch.object(mediamtx, "MEDIAMTX_API", ""):
        with pytest.raises(RuntimeError, match="MEDIAMTX_API"):
            mediamtx.remove_stream("ipcam-x")


def test_get_path_raises_when_api_unset():
    with patch.object(mediamtx, "MEDIAMTX_API", ""):
        with pytest.raises(RuntimeError, match="MEDIAMTX_API"):
            mediamtx.get_path("ipcam-x")


# ─── runOnDemand 조건부 transcode payload (패턴 C) ───


def test_register_posts_runondemand_payload():
    """register_stream 이 source 대신 runOnDemand transcode 커맨드를 보낸다."""
    with patch.object(mediamtx, "MEDIAMTX_API", "http://mtx:9997"), \
         patch("app.mediamtx.httpx.post") as post:
        post.return_value = MagicMock(status_code=200)
        mediamtx.register_stream("ipcam-abc", "rtsp://cam/stream1")

        _, kwargs = post.call_args
        body = kwargs["json"]
        # source 패스스루 아님 — runOnDemand 사용
        assert "source" not in body
        cmd = body["runOnDemand"]
        # 셸 없이 직접 ffmpeg (mediamtx 가 셸변수 $C/$V 를 먹어서 조건분기 불가)
        assert cmd.startswith("ffmpeg")
        # 카메라 rtsp 는 등록 시점 치환
        assert "rtsp://cam/stream1" in cmd
        # 항상 H.264 transcode (모든 코덱 호환 — passthrough 최적화 포기)
        assert "libx264" in cmd
        # 시간기반 keyframe 강제 — 저fps 카메라 WHEP join 지연 방지 (~2초 내 IDR)
        assert "force_key_frames" in cmd
        # mediamtx 런타임 변수는 literal($ 그대로)
        assert "$RTSP_PORT" in cmd and "$MTX_PATH" in cmd
        # on-demand 종료
        assert body["runOnDemandCloseAfter"] == "10s"


# ─── rtsp_url injection 가드 (shlex.quote 중립화 + 스킴 검증) ───


def test_register_rejects_non_rtsp_scheme():
    """rtsp/rtsps 아닌 스킴은 ValueError (POST 도달 전)."""
    with patch.object(mediamtx, "MEDIAMTX_API", "http://mtx:9997"), \
         patch("app.mediamtx.httpx.post") as post:
        with pytest.raises(ValueError, match="스킴"):
            mediamtx.register_stream("ipcam-x", "http://cam/stream")
        post.assert_not_called()


def test_register_accepts_rtsps_scheme():
    """rtsps:// (TLS) 스킴도 허용 — 일부 카메라가 암호화 RTSP 를 쓴다."""
    with patch.object(mediamtx, "MEDIAMTX_API", "http://mtx:9997"), \
         patch("app.mediamtx.httpx.post") as post:
        post.return_value = MagicMock(status_code=200)
        assert mediamtx.register_stream("ipcam-x", "rtsps://cam:322/stream") is True


@pytest.mark.parametrize("bad", [
    "rtsp://cam/stream\nmalicious",   # 개행 (헤더/명령 분리 표면)
    "rtsp://cam/stream\rmalicious",   # 캐리지리턴
    "rtsp://cam/stream\x00trunc",     # 널바이트 (C 문자열 절단)
])
def test_register_rejects_control_chars(bad):
    """제어문자(\\n \\r \\x00)는 ValueError (denylist) — POST 도달 전."""
    with patch.object(mediamtx, "MEDIAMTX_API", "http://mtx:9997"), \
         patch("app.mediamtx.httpx.post") as post:
        with pytest.raises(ValueError, match="금지문자"):
            mediamtx.register_stream("ipcam-x", bad)
        post.assert_not_called()


@pytest.mark.parametrize("evil", [
    "rtsp://cam/stream'; touch /tmp/pwned; echo '",  # quote breakout + 명령주입
    'rtsp://cam/stream"$(whoami)"',                   # command substitution
    "rtsp://cam/`id`",                                 # backtick
    "rtsp://cam/stream; echo hi",                      # 세미콜론 명령 분리
])
def test_register_rejects_shell_metachars(evil):
    """셸 메타문자(; $ ` | & ( ) ' " 등)는 denylist 로 ValueError — POST 도달 전.

    runOnDemand 는 셸 없이 직접 exec 되지만(mediamtx), mediamtx 의 $ 변수치환 +
    미래 셸-wrapping 대비 defense-in-depth 로 메타문자를 등록 시점에 거부한다.
    """
    with patch.object(mediamtx, "MEDIAMTX_API", "http://mtx:9997"), \
         patch("app.mediamtx.httpx.post") as post:
        with pytest.raises(ValueError, match="금지문자"):
            mediamtx.register_stream("ipcam-x", evil)
        post.assert_not_called()


def test_register_accepts_normal_rtsp_url():
    with patch.object(mediamtx, "MEDIAMTX_API", "http://mtx:9997"), \
         patch("app.mediamtx.httpx.post") as post:
        post.return_value = MagicMock(status_code=200)
        # 인증정보 포함 정상 URL 도 통과
        assert mediamtx.register_stream("ipcam-x", "rtsp://user:pass@192.168.0.10:554/h264") is True


# ─── P1 로그 평문 비번 누수 차단 (CEO #62) ───


def test_register_masks_password_in_log(caplog):
    """register_stream 의 등록 로그가 비번을 평문으로 남기지 않는다.

    버그: `→ %s` 로 rtsp_url 전체를 찍어 stdout/docker 로그에 비번 평문 노출.
    / 와 # 를 포함한 비번으로도 로그에 *** 만 남아야 한다.
    """
    with patch.object(mediamtx, "MEDIAMTX_API", "http://mtx:9997"), \
         patch("app.mediamtx.httpx.post") as post:
        post.return_value = MagicMock(status_code=200)
        with caplog.at_level(logging.INFO, logger="rtsp-streaming.mediamtx"):
            mediamtx.register_stream("ipcam-x", "rtsp://admin:pa/ss#word@10.0.0.5:554/cam")

    text = caplog.text
    assert "ipcam-x" in text  # 등록 로그가 실제로 찍혔는지
    assert "rtsp://admin:***@10.0.0.5:554/cam" in text  # 마스킹된 형태로
    for leak in ("pa/ss", "#word", "pa/ss#word"):
        assert leak not in text, f"로그 비번 평문 누수: {leak!r}"
