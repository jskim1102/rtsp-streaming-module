"""Ip CAM CRUD characterization + 16대 cap (net-new) 테스트.

CRUD list/create/update/delete/stats 는 추출 코드의 기존 동작을 고정(characterization).
16대 cap 은 net-new 로직 → 명시적 경계 테스트(16 OK, 17번째 409).
"""

import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def mtx():
    """ipcam.py 가 호출하는 mediamtx 함수를 mock — 실 httpx 호출 차단."""
    with patch("app.ipcam.register_stream") as register, \
         patch("app.ipcam.remove_stream") as remove:
        register.return_value = True
        yield {"register": register, "remove": remove}


@pytest.fixture()
def client(mtx):
    """임시 SQLite DB 에 ip_cams 테이블 생성 후 TestClient. 매 테스트 격리."""
    # 임시 DB 파일
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_url = f"sqlite:///{path}"

    # 라우터만 단독 마운트 (main.py 전체 배선과 독립 — #37 에서 따로 검증)
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


# ─── net-new: mediamtx 사이드이펙트 배선 (test-first) ───


def test_create_registers_mediamtx_path(client, mtx):
    cam = client.post("/api/ipcams", json={"name": "c", "rtsp_url": "rtsp://x/c"}).json()
    mtx["register"].assert_called_once_with(cam["stream_key"], "rtsp://x/c")


def test_update_rtsp_change_reregisters(client, mtx):
    cam = client.post("/api/ipcams", json={"name": "u", "rtsp_url": "rtsp://x/old"}).json()
    mtx["register"].reset_mock()
    mtx["remove"].reset_mock()
    client.put(f"/api/ipcams/{cam['id']}", json={"name": "u", "rtsp_url": "rtsp://x/new"})
    mtx["remove"].assert_called_once_with(cam["stream_key"])
    mtx["register"].assert_called_once_with(cam["stream_key"], "rtsp://x/new")


def test_update_no_rtsp_change_no_reregister(client, mtx):
    cam = client.post("/api/ipcams", json={"name": "u", "rtsp_url": "rtsp://x/same"}).json()
    mtx["register"].reset_mock()
    mtx["remove"].reset_mock()
    # name 만 변경, rtsp 동일 → mediamtx 재등록 안 함
    client.put(f"/api/ipcams/{cam['id']}", json={"name": "renamed", "rtsp_url": "rtsp://x/same"})
    mtx["remove"].assert_not_called()
    mtx["register"].assert_not_called()


def test_delete_removes_mediamtx_path(client, mtx):
    cam = client.post("/api/ipcams", json={"name": "d", "rtsp_url": "rtsp://x/d"}).json()
    mtx["remove"].reset_mock()
    client.delete(f"/api/ipcams/{cam['id']}")
    mtx["remove"].assert_called_once_with(cam["stream_key"])


# ─── net-new: stats mediamtx /v3/paths/get 기반 (test-first) ───


def test_stats_active_with_readers(client):
    cam = client.post("/api/ipcams", json={"name": "s", "rtsp_url": "rtsp://x/s"}).json()
    # mediamtx 가 ready=true + readers 2개 보고
    with patch("app.ipcam.get_path", return_value={"ready": True, "readers": [{}, {}]}):
        resp = client.get(f"/api/ipcams/{cam['stream_key']}/stats")
    assert resp.status_code == 200
    assert resp.json() == {"active": True, "readers": 2}


def test_stats_inactive_when_path_missing(client):
    cam = client.post("/api/ipcams", json={"name": "s", "rtsp_url": "rtsp://x/s"}).json()
    # path 없음 → None
    with patch("app.ipcam.get_path", return_value=None):
        resp = client.get(f"/api/ipcams/{cam['stream_key']}/stats")
    assert resp.status_code == 200
    assert resp.json() == {"active": False, "readers": 0}


def test_stats_inactive_when_not_ready(client):
    cam = client.post("/api/ipcams", json={"name": "s", "rtsp_url": "rtsp://x/s"}).json()
    # path 존재하나 아직 ready 아님 (source 연결 전)
    with patch("app.ipcam.get_path", return_value={"ready": False, "readers": []}):
        resp = client.get(f"/api/ipcams/{cam['stream_key']}/stats")
    assert resp.status_code == 200
    assert resp.json() == {"active": False, "readers": 0}


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


# ─── net-new: rtsp:// 스킴 검증 (injection 2중 방어 1단; 셸안전은 shlex.quote) ───


def test_create_rejects_non_rtsp_scheme_400(client):
    resp = client.post("/api/ipcams", json={"name": "bad", "rtsp_url": "http://x/stream"})
    assert resp.status_code == 400
    assert client.get("/api/ipcams").json() == []  # DB 오염 없음


def test_update_rejects_non_rtsp_scheme_400(client):
    cam = client.post("/api/ipcams", json={"name": "ok", "rtsp_url": "rtsp://x/ok"}).json()
    resp = client.put(f"/api/ipcams/{cam['id']}", json={"name": "ok", "rtsp_url": "ftp://x/evil"})
    assert resp.status_code == 400
    assert client.get("/api/ipcams").json()[0]["rtsp_url"] == "rtsp://x/ok"  # 기존 유지


def test_create_accepts_rtsp_url_with_metachars(client):
    # rtsp:// 스킴이면 셸 메타문자가 있어도 등록 성공 — shlex.quote 가 중립화.
    resp = client.post("/api/ipcams", json={"name": "ok", "rtsp_url": "rtsp://u:p@10.0.0.1:554/stream"})
    assert resp.status_code == 201


# ─── net-new: P1-3 mediamtx 등록 실패 시 rollback (성공처럼 보이는 실패 방지) ───


def test_create_rolls_back_when_mediamtx_register_fails(client, mtx):
    """register_stream=False → 503 + DB 미저장(롤백)."""
    mtx["register"].return_value = False
    resp = client.post("/api/ipcams", json={"name": "x", "rtsp_url": "rtsp://x/1"})
    assert resp.status_code == 503
    assert client.get("/api/ipcams").json() == []  # 롤백되어 흔적 없음


def test_create_503_when_mediamtx_api_unset(client, mtx):
    """MEDIAMTX_API 미설정(register_stream 이 RuntimeError) → 503 + 롤백."""
    mtx["register"].side_effect = RuntimeError("MEDIAMTX_API 미설정")
    resp = client.post("/api/ipcams", json={"name": "x", "rtsp_url": "rtsp://x/1"})
    assert resp.status_code == 503
    assert client.get("/api/ipcams").json() == []


# ─── net-new: P1-4 자격증명 마스킹 ───


def test_list_masks_rtsp_credentials(client):
    """목록 응답의 rtsp_url 비밀번호는 *** 로 마스킹 (평문 노출 차단)."""
    client.post("/api/ipcams", json={"name": "c", "rtsp_url": "rtsp://admin:secret@10.0.0.5:554/s"})
    url = client.get("/api/ipcams").json()[0]["rtsp_url"]
    assert url == "rtsp://admin:***@10.0.0.5:554/s"
    assert "secret" not in url


def test_update_masked_url_preserves_credentials(client, mtx):
    """수정 시 마스킹된 URL 그대로 들어오면(미수정) 기존 자격증명 유지 + 재등록 안 함."""
    cam = client.post(
        "/api/ipcams", json={"name": "c", "rtsp_url": "rtsp://admin:secret@10.0.0.5:554/s"}
    ).json()
    masked = cam["rtsp_url"]  # rtsp://admin:***@10.0.0.5:554/s
    mtx["register"].reset_mock()
    mtx["remove"].reset_mock()

    # 이름만 변경, URL 은 마스킹된 값 그대로 → 자격증명 보존, mediamtx 재등록 없음
    resp = client.put(f"/api/ipcams/{cam['id']}", json={"name": "renamed", "rtsp_url": masked})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"
    assert resp.json()["rtsp_url"] == masked  # 여전히 마스킹 (저장된 실값은 secret 그대로)
    mtx["remove"].assert_not_called()
    mtx["register"].assert_not_called()


def test_update_masked_password_with_changed_host_applies_change(client, mtx):
    """버그재현(CEO #56-1): 마스킹된 비번(***)은 유지한 채 host/path 만 바꿔 저장하면
    그 변경이 DB·mediamtx 에 실제 반영돼야 한다.

    기존 버그: `:***@` 가 들어오면 URL '전체' 를 old 로 되돌려, 함께 바뀐 host/path 까지
    사라졌다 → "주소 바꿔도 반영 안 됨". 자격증명 카메라(현장 대부분)에서 항상 재현.
    """
    cam = client.post(
        "/api/ipcams", json={"name": "c", "rtsp_url": "rtsp://admin:secret@10.0.0.5:554/s"}
    ).json()
    masked = cam["rtsp_url"]
    assert masked == "rtsp://admin:***@10.0.0.5:554/s"
    mtx["register"].reset_mock()
    mtx["remove"].reset_mock()

    # host 만 .5 → .9 로 변경, 비번은 *** 그대로 (사용자가 비번 재입력 안 함)
    changed = "rtsp://admin:***@10.0.0.9:554/s"
    resp = client.put(f"/api/ipcams/{cam['id']}", json={"name": "c", "rtsp_url": changed})
    assert resp.status_code == 200
    # 응답(마스킹)에 새 host 반영
    assert resp.json()["rtsp_url"] == "rtsp://admin:***@10.0.0.9:554/s"
    # mediamtx 재등록: 새 host + 보존된 실제 비번(secret)
    mtx["remove"].assert_called_once_with(cam["stream_key"])
    mtx["register"].assert_called_once_with(cam["stream_key"], "rtsp://admin:secret@10.0.0.9:554/s")
    # DB 재조회 — list 는 마스킹되지만 host 가 .9 로 바뀌어야 함
    assert client.get("/api/ipcams").json()[0]["rtsp_url"] == "rtsp://admin:***@10.0.0.9:554/s"


# ─── net-new: P1 보안 핫픽스 — 예약문자(/ #) 비번 마스킹 누수 (CEO #60) ───


def test_list_masks_password_with_reserved_chars_no_leak(client):
    """버그재현(CEO #60): 비번에 / 나 # 가 있으면 urlsplit 이 비번을 path/fragment 로
    끊어, 마스킹돼도 비번 일부가 GET 응답에 평문 누수했다(인증 없는 API → 비번 노출).
    last-@ 마스킹은 예약문자가 있어도 비번 전체를 *** 로 가린다.
    """
    pw = "pa/ss#word"
    client.post(
        "/api/ipcams", json={"name": "c", "rtsp_url": f"rtsp://admin:{pw}@10.0.0.5:554/cam"}
    )
    url = client.get("/api/ipcams").json()[0]["rtsp_url"]
    assert url == "rtsp://admin:***@10.0.0.5:554/cam"
    # 비번의 어떤 조각도 응답에 남으면 안 됨 (path/fragment 누수 포함)
    for frag in (pw, "ss", "word"):
        assert frag not in url, f"비번 조각 누수: {frag!r} in {url!r}"


def test_update_masked_reserved_char_password_changed_host(client, mtx):
    """/·# 비번 카메라도 *** 유지한 채 주소만 바꿔 저장 → 변경 반영 + 실제 비번 보존(restore 견고)."""
    cam = client.post(
        "/api/ipcams", json={"name": "c", "rtsp_url": "rtsp://admin:pa/ss#x@10.0.0.5:554/cam"}
    ).json()
    assert cam["rtsp_url"] == "rtsp://admin:***@10.0.0.5:554/cam"
    mtx["register"].reset_mock()
    mtx["remove"].reset_mock()

    client.put(
        f"/api/ipcams/{cam['id']}",
        json={"name": "c", "rtsp_url": "rtsp://admin:***@10.0.0.7:554/cam"},
    )
    # 새 host + 끊기지 않은 실제 비번(pa/ss#x)으로 mediamtx 재등록
    mtx["register"].assert_called_once_with(
        cam["stream_key"], "rtsp://admin:pa/ss#x@10.0.0.7:554/cam"
    )
    assert client.get("/api/ipcams").json()[0]["rtsp_url"] == "rtsp://admin:***@10.0.0.7:554/cam"


def test_mask_restore_roundtrip_special_char_passwords():
    """mask→restore 가 특수·예약문자 비번을 누수 없이 왕복하는지 (헬퍼 직접 단위).

    수용기준 문자셋: @ : % 공백 ! / # (공백은 API _validate 가 막지만 헬퍼는 견고해야 함).
    """
    from app.ipcam import _restore_masked_password, mask_rtsp_credentials

    for pw in ["p@ss", "pa:ss", "p%2Fss", "pa ss", "p!ss", "pa/ss", "pa#ss", "a/b#c?d@e"]:
        original = f"rtsp://admin:{pw}@10.0.0.5:554/cam"
        masked = mask_rtsp_credentials(original)
        assert masked == "rtsp://admin:***@10.0.0.5:554/cam", f"{pw!r} 마스킹 불완전: {masked!r}"
        assert pw not in masked, f"{pw!r} 평문 누수: {masked!r}"
        # 마스킹된 값으로(주소 미변경) 저장 → 실제 비번 복원 = 원본
        restored = _restore_masked_password(masked, original)
        assert restored == original, f"{pw!r} 복원 실패: {restored!r}"


# ─── net-new: P1 — validate 에러 메시지(→400 응답 본문)에 비번 평문 반사 (CEO #66) ───


def test_create_forbidden_char_400_masks_password_in_detail(client):
    """버그재현(CEO #66): 금지문자+비번 url 등록 → 400 응답 본문에 비번 평문 반사됐다.
    이제 에러 메시지의 url 도 마스킹된다(***). (`;` = 셸메타 금지문자, 비번에 위치)
    """
    resp = client.post(
        "/api/ipcams", json={"name": "x", "rtsp_url": "rtsp://admin:se;cret@10.0.0.5:554/cam"}
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "se;cret" not in detail and "secret" not in detail  # 평문 비번 0
    assert "***" in detail  # 마스킹된 형태로 들어감
    assert client.get("/api/ipcams").json() == []  # DB 오염 없음


def test_create_bad_scheme_400_masks_password_in_detail(client):
    """스킴 에러 메시지도 비번 마스킹 (http:// 인데 자격증명 포함된 경우)."""
    resp = client.post(
        "/api/ipcams", json={"name": "x", "rtsp_url": "http://admin:secret@10.0.0.5/cam"}
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "secret" not in detail
    assert "***" in detail


def test_update_forbidden_char_400_masks_password_in_detail(client):
    """update 경로의 validate 에러도 동일하게 비번 마스킹."""
    cam = client.post(
        "/api/ipcams", json={"name": "ok", "rtsp_url": "rtsp://admin:good@10.0.0.5:554/s"}
    ).json()
    resp = client.put(
        f"/api/ipcams/{cam['id']}",
        json={"name": "ok", "rtsp_url": "rtsp://admin:ba|d@10.0.0.9:554/s"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "ba|d" not in detail and "***" in detail
