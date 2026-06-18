import { useState, useEffect } from "react";
import type { Cam } from "../pages/CamerasPage";

interface Props {
  open: boolean;
  editCam: Cam | null;
  onClose: () => void;
  onSave: (name: string, rtspUrl: string) => void;
}

export default function CameraFormModal({ open, editCam, onClose, onSave }: Props) {
  const [name, setName] = useState("");
  const [rtspUrl, setRtspUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setName(editCam?.name ?? "");
      setRtspUrl(editCam?.rtsp_url ?? "");
      setError("");
    }
  }, [open, editCam]);

  if (!open) return null;

  // onSave 는 부모(CamerasPage)에서 POST/PUT /api/ipcams 로 처리한다.
  function handleSubmit() {
    if (!name.trim() || !rtspUrl.trim()) {
      setError("이름과 RTSP URL을 입력하세요.");
      return;
    }
    onSave(name.trim(), rtspUrl.trim());
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{editCam ? "카메라 수정" : "카메라 등록"}</h2>

        <div className="field">
          <label>카메라 이름</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="예: 정문 입구 카메라"
          />
        </div>

        <div className="field">
          <label>RTSP URL</label>
          <input
            value={rtspUrl}
            onChange={(e) => setRtspUrl(e.target.value)}
            placeholder="rtsp://192.168.0.100:554/stream1"
          />
          <p className="hint">
            형식 — rtsp://[user:pass@]IP:PORT/PATH · 지원 코덱 H.264 / H.265
          </p>
          {editCam && rtspUrl.includes(":***@") && (
            <p className="hint">
              ⚠️ <code>***</code> = 기존 비밀번호 유지. URL·비밀번호를 변경하려면 전체
              rtsp:// 를 다시 입력하세요(<code>***</code> 가 남아 있으면 URL 변경은 무시됩니다).
            </p>
          )}
        </div>

        {error && <p className="form-error">{error}</p>}

        <div className="modal-actions">
          <button onClick={onClose}>취소</button>
          <button className="primary" onClick={handleSubmit}>
            {editCam ? "저장" : "등록"}
          </button>
        </div>
      </div>
    </div>
  );
}
