"""영상 캡처 + 스트리밍 패키지.

IP CAM(RTSP URL) 을 opencv(FFMPEG)로 디코딩해 raw JPEG 프레임으로 제공한다.
"""

from app.streaming.capture import VideoCaptureThread
from app.streaming.manager import StreamManager, manager

__all__ = ["VideoCaptureThread", "StreamManager", "manager"]
