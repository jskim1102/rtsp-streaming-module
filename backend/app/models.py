import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _generate_stream_key() -> str:
    """등록용 고유 스트림 키 생성"""
    return f"ipcam-{uuid.uuid4().hex[:8]}"


class IpCam(Base):
    __tablename__ = "ip_cams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rtsp_url: Mapped[str] = mapped_column(String(500), nullable=False)
    stream_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, default=_generate_stream_key)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
