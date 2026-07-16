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
  readers: number;
}

const MAX_IPCAMS_FALLBACK = 16; // spec F4 — /api/config 로딩 전 기본값. 실제 cap 은 백엔드 env.

// 실패 응답에서 backend detail(비어있지 않은 문자열)만 노출, 없거나 비문자열·공백이면 fallback.
// detail 은 <p>{error}</p> 로 렌더되므로 문자열 보장 필수 — 객체/배열 detail 렌더 크래시 차단.
async function errorDetail(resp: Response, fallback: string): Promise<string> {
  // .catch(null) + ?. — 본문이 JSON `null` 이거나 파싱 실패여도 안전(널 역참조 크래시 차단).
  const body = await resp.json().catch(() => null);
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

export default function CamerasPage() {
  const [cams, setCams] = useState<Cam[]>([]);
  const [stats, setStats] = useState<Record<string, Stat>>({});
  // 실측 FPS — 그리드의 WhepPlayer 가 WebRTC getStats 로 올려주는 카메라별 디코딩 프레임레이트.
  const [fps, setFps] = useState<Record<string, number>>({});
  // 등록 cap — 백엔드 /api/config(MAX_IPCAMS env)에서 받음. 프론트 하드코딩 제거(P2-1).
  const [maxIpcams, setMaxIpcams] = useState(MAX_IPCAMS_FALLBACK);
  const [formOpen, setFormOpen] = useState(false);
  const [editCam, setEditCam] = useState<Cam | null>(null);
  const [error, setError] = useState("");
  // 카메라별 remount epoch — RTSP 변경 편집 성공 시 bump(→ CameraGrid key 변경 → 셀 remount).
  // 응답 rtsp_url 은 마스킹(:***@)이라 비번-only 변경을 서버 응답으론 못 잡으므로 이 신호를 쓴다.
  const [playerEpoch, setPlayerEpoch] = useState<Record<number, number>>({});

  const fetchCams = useCallback(async () => {
    const resp = await fetch(`${apiBase()}/api/ipcams`);
    if (!resp.ok) return;
    setCams(await resp.json());
  }, []);

  useEffect(() => {
    fetchCams();
  }, [fetchCams]);

  // 등록 cap 을 백엔드에서 1회 로딩 (없으면 fallback 유지).
  useEffect(() => {
    fetch(`${apiBase()}/api/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cfg?.max_ipcams) setMaxIpcams(cfg.max_ipcams);
      })
      .catch(() => {});
  }, []);

  // stats 1초 polling — 등록 카메라별 {active, readers} (mediamtx path 상태).
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      const entries = await Promise.all(
        cams.map(async (c) => {
          try {
            const resp = await fetch(`${apiBase()}/api/ipcams/${c.stream_key}/stats`);
            if (!resp.ok) return [c.stream_key, { active: false, readers: 0 }] as const;
            return [c.stream_key, (await resp.json()) as Stat] as const;
          } catch {
            return [c.stream_key, { active: false, readers: 0 }] as const;
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
  const atCap = cams.length >= maxIpcams;

  const handleFps = useCallback((key: string, f: number) => {
    setFps((prev) => ({ ...prev, [key]: f }));
  }, []);

  // 등록/수정 — 성공 시 null, 실패 시 에러메시지 반환(모달이 표시 + 로딩상태 제어, #124).
  async function handleSave(name: string, rtspUrl: string): Promise<string | null> {
    if (editCam) {
      // 사용자가 입력한 url 이 기존값(마스킹 :***@ 포함)과 다르면 스트림 변경(비번·주소 등).
      // 이름만 바꾼 편집은 여기서 false → remount 하지 않는다(불필요한 WHEP 재연결/깜빡임 방지).
      const urlChanged = rtspUrl !== editCam.rtsp_url;
      const resp = await fetch(`${apiBase()}/api/ipcams/${editCam.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, rtsp_url: rtspUrl }),
      });
      if (!resp.ok) {
        // 백엔드 detail(예: 마스킹 *** 인 채 주소 변경 → 실비번 재입력 안내)을 그대로 노출.
        return await errorDetail(resp, "카메라 수정에 실패했습니다.");
      }
      // RTSP 변경 성공 시에만 셀 remount 신호 bump(비번-only 편집도 새 자격증명으로 WHEP 재연결).
      if (urlChanged) {
        const id = editCam.id;
        setPlayerEpoch((prev) => ({ ...prev, [id]: (prev[id] ?? 0) + 1 }));
      }
    } else {
      const resp = await fetch(`${apiBase()}/api/ipcams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, rtsp_url: rtspUrl }),
      });
      if (resp.status === 409) {
        return await errorDetail(resp, `최대 ${maxIpcams}대까지 등록할 수 있습니다`);
      }
      // 409 외 실패(예: 503 mediamtx 미가용, 400 URL 검증)도 backend detail 노출 — PUT 경로와 일관.
      if (!resp.ok) return await errorDetail(resp, "카메라 등록에 실패했습니다.");
    }
    await fetchCams();
    return null;
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
                <td>{active && fps[cam.stream_key] != null ? fps[cam.stream_key].toFixed(1) : "—"}</td>
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

      <hr className="grid-divider" />
      <CameraGrid cams={cams} onFps={handleFps} epochs={playerEpoch} />

      <CameraFormModal
        open={formOpen}
        editCam={editCam}
        onClose={() => setFormOpen(false)}
        onSave={handleSave}
      />
    </main>
  );
}
