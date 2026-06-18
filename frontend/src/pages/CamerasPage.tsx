import { useState, useEffect, useCallback } from "react";
import { apiBase } from "../hooks/useApi";
import CameraFormModal from "../components/CameraFormModal";
import CameraGrid from "../components/CameraGrid";

export interface Cam {
  id: number;
  name: string;
  rtsp_url: string;
  stream_key: string;
  created_at: string;
}

interface Stat {
  active: boolean;
  source_fps: number;
}

const MAX_IPCAMS = 16; // spec F4 — 초과 시 등록 거부. 백엔드 409 와 동일 cap.

export default function CamerasPage() {
  const [cams, setCams] = useState<Cam[]>([]);
  const [stats, setStats] = useState<Record<string, Stat>>({});
  const [formOpen, setFormOpen] = useState(false);
  const [editCam, setEditCam] = useState<Cam | null>(null);
  const [error, setError] = useState("");

  const fetchCams = useCallback(async () => {
    const resp = await fetch(`${apiBase()}/api/ipcams`);
    if (!resp.ok) return;
    setCams(await resp.json());
  }, []);

  useEffect(() => {
    fetchCams();
  }, [fetchCams]);

  // stats 1초 polling — 등록 카메라별 {active, source_fps}.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      const entries = await Promise.all(
        cams.map(async (c) => {
          try {
            const resp = await fetch(`${apiBase()}/api/ipcams/${c.stream_key}/stats`);
            if (!resp.ok) return [c.stream_key, { active: false, source_fps: 0 }] as const;
            return [c.stream_key, (await resp.json()) as Stat] as const;
          } catch {
            return [c.stream_key, { active: false, source_fps: 0 }] as const;
          }
        })
      );
      if (!cancelled) setStats(Object.fromEntries(entries));
    }
    poll();
    const timer = setInterval(poll, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [cams]);

  const online = cams.filter((c) => stats[c.stream_key]?.active).length;
  const atCap = cams.length >= MAX_IPCAMS;

  async function handleSave(name: string, rtspUrl: string) {
    setError("");
    if (editCam) {
      const resp = await fetch(`${apiBase()}/api/ipcams/${editCam.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, rtsp_url: rtspUrl }),
      });
      if (!resp.ok) {
        setError("카메라 수정에 실패했습니다.");
        return;
      }
    } else {
      const resp = await fetch(`${apiBase()}/api/ipcams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, rtsp_url: rtspUrl }),
      });
      if (resp.status === 409) {
        const body = await resp.json().catch(() => ({}));
        setError(body.detail ?? `최대 ${MAX_IPCAMS}대까지 등록할 수 있습니다`);
        return;
      }
      if (!resp.ok) {
        setError("카메라 등록에 실패했습니다.");
        return;
      }
    }
    await fetchCams();
  }

  async function deleteCam(cam: Cam) {
    if (!window.confirm(`${cam.name} 삭제?`)) return;
    const resp = await fetch(`${apiBase()}/api/ipcams/${cam.id}`, { method: "DELETE" });
    if (!resp.ok) {
      setError("카메라 삭제에 실패했습니다.");
      return;
    }
    await fetchCams();
  }

  return (
    <main className="app">
      <header className="page-head">
        <div>
          <h1>RTSP Streaming</h1>
          <p className="subtitle">카메라 관리</p>
        </div>
        <button
          className="primary"
          disabled={atCap}
          onClick={() => {
            setEditCam(null);
            setFormOpen(true);
          }}
        >
          + 카메라 등록
        </button>
      </header>

      {error && <p className="form-error">{error}</p>}

      <section className="summary">
        <div className="summary-cell">
          <div className="summary-label">전체 카메라</div>
          <div className="summary-value">{cams.length}</div>
        </div>
        <div className="summary-cell">
          <div className="summary-label">온라인</div>
          <div className="summary-value">
            {online}
            <span className="summary-sub"> / {cams.length}</span>
          </div>
        </div>
      </section>

      <table>
        <thead>
          <tr>
            <th style={{ width: 180 }}>카메라</th>
            <th>RTSP URL</th>
            <th style={{ width: 110 }}>상태</th>
            <th style={{ width: 80 }}>FPS</th>
            <th style={{ width: 140, textAlign: "right" }}>관리</th>
          </tr>
        </thead>
        <tbody>
          {cams.map((cam) => {
            const st = stats[cam.stream_key];
            const active = st?.active ?? false;
            return (
              <tr key={cam.id}>
                <td>
                  <div className="cam-id">CAM-{String(cam.id).padStart(2, "0")}</div>
                  <div className="cam-name">{cam.name}</div>
                </td>
                <td className="url-cell">{cam.rtsp_url}</td>
                <td>
                  <span className={active ? "status status-on" : "status status-off"}>
                    {active ? "● 온라인" : "● 오프라인"}
                  </span>
                </td>
                <td>{active ? (st?.source_fps ?? 0).toFixed(1) : "—"}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button
                    onClick={() => {
                      setEditCam(cam);
                      setFormOpen(true);
                    }}
                  >
                    수정
                  </button>{" "}
                  <button className="danger" onClick={() => deleteCam(cam)}>
                    삭제
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2 className="grid-heading">실시간 그리드</h2>
      <CameraGrid cams={cams} />

      <CameraFormModal
        open={formOpen}
        editCam={editCam}
        onClose={() => setFormOpen(false)}
        onSave={handleSave}
      />
    </main>
  );
}
