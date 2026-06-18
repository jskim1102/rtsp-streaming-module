"""단일 영상 소스의 캡처 + JPEG 인코딩 스레드.

`source` 가 `int` 면 V4L2 웹캠, `str` 이면 RTSP 등 OpenCV 가 인식하는 URL.
이 모듈은 raw 영상만 다룬다 — 추론 제출 훅은 제거됨 (WS-JPEG 단일 경로).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional, Union

import cv2

logger = logging.getLogger("rtsp-streaming.capture")

# Type alias
SourceType = Union[int, str]


class VideoCaptureThread:
    """단일 영상 소스의 캡처 루프.

    - 백그라운드 스레드에서 OpenCV `VideoCapture` 로 프레임 읽기
    - JPEG 인코딩 후 내부 버퍼에 저장 → WebSocket 핸들러가 가져감
    - ref_count 기반 lifecycle (여러 클라이언트 동시 시청 가능)

    `source` 가 `int` (예: 0) 면 V4L2 웹캠, `str` (예: "rtsp://...") 면 IP CAM.
    """

    # FPS 측정 슬라이딩 윈도우 — 최근 5초 동안의 frame 수를 5로 나눠서 fps
    _STATS_WINDOW_SEC = 5.0
    # deque maxlen — 5초 × 60fps 여유로 잡음 (RTSP 가 아주 높은 fps 보내도 안전)
    _STATS_DEQUE_MAXLEN = 600

    def __init__(
        self,
        source_id: str,
        source: SourceType,
        *,
        jpeg_quality: int = 70,
    ) -> None:
        self.source_id = source_id
        self.source = source
        self._jpeg_quality = jpeg_quality

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: bytes = b""
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ref_count = 0
        self._open_event = threading.Event()

        # FPS 측정용 — 슬라이딩 윈도우 timestamp 저장
        self._source_ts: deque[float] = deque(maxlen=self._STATS_DEQUE_MAXLEN)
        self._stats_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────

    def start(self) -> bool:
        """캡처 시작. 이미 실행 중이면 ref_count 만 증가."""
        with self._lock:
            self._ref_count += 1
            if self._running:
                return True

        self._running = True
        self._open_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name=f"capture-{self.source_id}",
        )
        self._thread.start()

        # RTSP 는 연결까지 시간 걸릴 수 있어 timeout 넉넉히
        timeout = 15.0 if isinstance(self.source, str) else 5.0
        self._open_event.wait(timeout=timeout)

        if not self._cap or not self._cap.isOpened():
            self._running = False
            with self._lock:
                self._ref_count -= 1
            return False
        return True

    def stop(self) -> None:
        """ref_count 감소. 0 이 되면 캡처 종료."""
        with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            if self._ref_count > 0:
                return
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def force_stop(self) -> None:
        """ref_count 무시하고 즉시 종료 (서버 셧다운 시)."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    # ── 외부 조회 ────────────────────────────────────────────────

    def get_frame(self) -> bytes:
        """최신 JPEG 프레임 반환."""
        with self._lock:
            return self._frame

    @property
    def is_running(self) -> bool:
        return self._running

    def get_source_fps(self) -> float:
        """카메라 원본 fps — 최근 5초 슬라이딩 윈도우. cap.read() 가 성공한 비율."""
        now = time.time()
        cutoff = now - self._STATS_WINDOW_SEC
        with self._stats_lock:
            n = sum(1 for t in self._source_ts if t >= cutoff)
        return round(n / self._STATS_WINDOW_SEC, 1)

    # ── 내부 ────────────────────────────────────────────────────

    def _open_capture(self) -> cv2.VideoCapture:
        """source 종류에 맞춰 OpenCV backend 선택."""
        if isinstance(self.source, int):
            return cv2.VideoCapture(self.source, cv2.CAP_V4L2)
        # RTSP 등 URL — FFMPEG backend 가 timeout 처리 강함
        return cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)

    def _capture_loop(self) -> None:
        """캡처 + JPEG 인코딩 (단일 스레드)."""
        cap = self._open_capture()
        self._cap = cap
        self._open_event.set()

        if not cap.isOpened():
            logger.error("Capture %s 열기 실패: source=%s", self.source_id, self.source)
            self._running = False
            return

        logger.info("Capture %s 시작 (source=%s)", self.source_id, self.source)
        try:
            while self._running and cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue

                now = time.time()

                # ── source_fps 측정 — RTSP 가 보내는 원본 frame 수신 시점 기록
                with self._stats_lock:
                    self._source_ts.append(now)

                # raw JPEG 인코딩 — WS 핸들러가 binary 로 그대로 송출
                ok, buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
                )
                if ok:
                    with self._lock:
                        self._frame = buf.tobytes()
        except Exception:
            logger.exception("Capture %s 루프 예외", self.source_id)
        finally:
            cap.release()
            self._cap = None
            self._running = False
            logger.info("Capture %s 종료", self.source_id)
