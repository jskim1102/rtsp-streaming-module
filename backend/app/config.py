import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# backend/.env 를 로드
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# 빈 문자열(set-but-empty)도 미설정으로 취급해 안전기본 폴백 (codex #3).
#   os.getenv(k, default) 는 k 가 "" 면 ""(빈값)을 그대로 돌려준다 → CORS_ORIGINS="" → [""]
#   (기본 * 아님 → CORS 차단), MAX_IPCAMS="" → int("") → ValueError(import 크래시).
#   `or` 로 빈값=거짓 → 기본값으로 폴백한다.
CORS_ORIGINS: str = os.getenv("CORS_ORIGINS") or "*"

_raw_max_ipcams = int(os.getenv("MAX_IPCAMS") or "16")
MAX_IPCAMS: int = max(1, min(64, _raw_max_ipcams))

# mediamtx API 주소 — 하드코딩 fallback 을 두지 않는다(빈 문자열 = 미설정).
# Docker compose 가 environment 블록으로 `http://mediamtx:9997` 를 주입하고,
# 로컬 실행 시에는 backend/.env 에 설정한다. 실제로 호출하는 app.mediamtx 가
# 미설정이면 명시 에러를 낸다(import 시점엔 raise 안 함 — 순수 import/테스트 허용).
MEDIAMTX_API: str = os.getenv("MEDIAMTX_API", "")

# mediamtx 인증(#100) — backend user 로 API 호출 시 Basic auth. 비번 비우면 무인증(로컬/테스트 하위호환).
MEDIAMTX_BACKEND_USER: str = os.getenv("MEDIAMTX_BACKEND_USER", "backend")
MEDIAMTX_BACKEND_PASS: str = os.getenv("MEDIAMTX_BACKEND_PASS", "")

# WebRTC 외부접속 광고 호스트(공인 IP). mediamtx.yml 의 webrtcAdditionalHosts 로
# 주입된다. 미설정이면 mediamtx 가 컨테이너 내부 주소만 광고 → 외부에서 영상 안 나옴.
MEDIAMTX_WEBRTC_HOST: str = os.getenv("MEDIAMTX_WEBRTC_HOST", "")

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging() -> logging.Logger:
    """애플리케이션 로거 설정"""
    logger = logging.getLogger("rtsp-streaming")
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s  %(name)s — %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)

    return logger


logger = setup_logging()

if _raw_max_ipcams != MAX_IPCAMS:
    logger.warning("MAX_IPCAMS=%d → %d 로 보정됨 (허용 범위: 1~64)", _raw_max_ipcams, MAX_IPCAMS)
