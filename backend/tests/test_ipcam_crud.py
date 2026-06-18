"""Ip CAM CRUD characterization + 16대 cap (net-new) 테스트.

CRUD list/create/update/delete/stats 는 추출 코드의 기존 동작을 고정(characterization).
16대 cap 은 net-new 로직 → 명시적 경계 테스트(16 OK, 17번째 409).
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def client():
    """임시 SQLite DB 에 ip_cams 테이블 생성 후 TestClient. 매 테스트 격리."""
    # 임시 DB 파일
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_url = f"sqlite:///{path}"

    # 라우터만 단독 마운트 (main.py 전체 배선과 독립 — #21 에서 따로 검증)
    from fastapi import FastAPI

    from app.database import Base, get_db
    from app.ipcam import router as ipcam_router

    app = FastAPI()
    app.include_router(ipcam_router)

    engine = create_engine(test_url, connect_args={"check_same_thread": False})
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()
    os.unlink(path)


def test_create_returns_201_with_stream_key(client):
    resp = client.post("/api/ipcams", json={"name": "정문", "rtsp_url": "rtsp://x/1"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "정문"
    assert body["rtsp_url"] == "rtsp://x/1"
    assert body["stream_key"].startswith("ipcam-")
    assert "id" in body and "created_at" in body


def test_list_returns_created_cams_in_id_order(client):
    client.post("/api/ipcams", json={"name": "a", "rtsp_url": "rtsp://x/a"})
    client.post("/api/ipcams", json={"name": "b", "rtsp_url": "rtsp://x/b"})
    resp = client.get("/api/ipcams")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["a", "b"]


def test_update_changes_name_and_url(client):
    cam = client.post("/api/ipcams", json={"name": "old", "rtsp_url": "rtsp://x/old"}).json()
    resp = client.put(f"/api/ipcams/{cam['id']}", json={"name": "new", "rtsp_url": "rtsp://x/new"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new"
    assert resp.json()["rtsp_url"] == "rtsp://x/new"


def test_update_missing_returns_404(client):
    resp = client.put("/api/ipcams/999", json={"name": "x", "rtsp_url": "rtsp://x/x"})
    assert resp.status_code == 404


def test_delete_removes_cam(client):
    cam = client.post("/api/ipcams", json={"name": "d", "rtsp_url": "rtsp://x/d"}).json()
    resp = client.delete(f"/api/ipcams/{cam['id']}")
    assert resp.status_code == 204
    assert client.get("/api/ipcams").json() == []


def test_delete_missing_returns_404(client):
    resp = client.delete("/api/ipcams/999")
    assert resp.status_code == 404


def test_stats_inactive_when_no_capture(client):
    cam = client.post("/api/ipcams", json={"name": "s", "rtsp_url": "rtsp://x/s"}).json()
    resp = client.get(f"/api/ipcams/{cam['stream_key']}/stats")
    assert resp.status_code == 200
    # 캡처 미동작 → active False, source_fps 만 (inference_fps 떼냄)
    assert resp.json() == {"active": False, "source_fps": 0.0}


# ─── net-new: 16대 cap (test-first) ───


def test_can_register_up_to_max_ipcams(client):
    from app.config import MAX_IPCAMS

    for i in range(MAX_IPCAMS):
        resp = client.post("/api/ipcams", json={"name": f"cam{i}", "rtsp_url": f"rtsp://x/{i}"})
        assert resp.status_code == 201, f"등록 {i+1}/{MAX_IPCAMS} 실패: {resp.text}"
    assert len(client.get("/api/ipcams").json()) == MAX_IPCAMS


def test_register_over_cap_returns_409(client):
    from app.config import MAX_IPCAMS

    for i in range(MAX_IPCAMS):
        client.post("/api/ipcams", json={"name": f"cam{i}", "rtsp_url": f"rtsp://x/{i}"})

    # MAX_IPCAMS+1 번째 → 409
    resp = client.post("/api/ipcams", json={"name": "over", "rtsp_url": "rtsp://x/over"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == f"최대 {MAX_IPCAMS}대까지 등록할 수 있습니다"
