"""모든 영상 소스의 통합 매니저.

- 캡처 스레드들을 source_id 별로 관리
- WS 핸들러가 source_id 로 최신 JPEG 프레임 조회
- 추론(InferenceWorker/dispatch)은 제거됨 — raw JPEG 단일 경로.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.streaming.capture import SourceType, VideoCaptureThread

logger = logging.getLogger("rtsp-streaming.manager")


class StreamManager:
    """비디오 소스(IP CAM) 통합 관리.

    싱글톤으로 사용 (`from app.streaming import manager`).
    서버 lifespan 시작/종료에서 `startup()` / `shutdown()` 호출.
    """

    def __init__(self, jpeg_quality: int = 70) -> None:
        self._captures: dict[str, VideoCaptureThread] = {}
        self._lock = threading.Lock()
        self._jpeg_quality = jpeg_quality

    # ── lifecycle ────────────────────────────────────────────────

    def startup(self) -> None:
        """매니저 기동."""
        logger.info("StreamManager started")

    def shutdown(self) -> None:
        """모든 캡처 정리."""
        with self._lock:
            captures = list(self._captures.values())
            self._captures.clear()
        for cap in captures:
            cap.force_stop()
            logger.info("Capture %s 강제 종료", cap.source_id)
        logger.info("StreamManager shutdown 완료")

    # ── 캡처 시작/종료 (라우터에서 호출) ─────────────────────────

    def start_capture(self, source_id: str, source: SourceType) -> bool:
        """source_id 의 캡처 시작 (없으면 생성). ref_count 증가."""
        with self._lock:
            if source_id not in self._captures:
                self._captures[source_id] = VideoCaptureThread(
                    source_id=source_id,
                    source=source,
                    jpeg_quality=self._jpeg_quality,
                )
        return self._captures[source_id].start()

    def stop_capture(self, source_id: str) -> None:
        with self._lock:
            cap = self._captures.get(source_id)
        if cap:
            cap.stop()

    def get_frame(self, source_id: str) -> bytes:
        with self._lock:
            cap = self._captures.get(source_id)
        if cap:
            return cap.get_frame()
        return b""

    def get_capture_stats(self, source_id: str) -> Optional[dict]:
        """캡처 중인 source 의 source_fps. 캡처 미동작이면 None.

        - source_fps: RTSP 가 실제로 보내는 frame 속도 (cap.read 성공률)
        """
        with self._lock:
            cap = self._captures.get(source_id)
        if not cap or not cap.is_running:
            return None

        return {
            "source_fps": cap.get_source_fps(),
        }


# 싱글톤 — main.py 에서 startup/shutdown 호출
manager = StreamManager()
