import type { Cam } from "../pages/CamerasPage";
import { useWebSocket } from "../hooks/useWebSocket";

// 사용자 오버라이드(게이트2) — 1줄 최대 4칸, 4 채워지면 다음 줄로 wrap.
// (이전: deepeye-pose 추출 ≤1→1/≤2→2/≤4→2/≤9→3/else→4. spec Decisions 동기화 필요.)
function getGridColumns(count: number): number {
  return Math.min(Math.max(count, 1), 4);
}

interface Props {
  cams: Cam[];
}

// 셀마다 독립 WS 연결 — binary JPEG 프레임을 <img> 로 렌더, 끊기면 placeholder.
function GridCell({ cam }: { cam: Cam }) {
  const { imgSrc } = useWebSocket(`/api/ipcams/${cam.stream_key}/ws`);

  return (
    <div className="grid-cell">
      <span className="grid-cell-name">{cam.name}</span>
      {imgSrc ? (
        <img src={imgSrc} alt={cam.name} />
      ) : (
        <span className="grid-cell-nosignal">신호 없음</span>
      )}
    </div>
  );
}

export default function CameraGrid({ cams }: Props) {
  if (cams.length === 0) {
    return <p className="grid-empty">등록된 카메라가 없습니다.</p>;
  }

  const columns = getGridColumns(cams.length);

  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
      {cams.map((cam) => (
        <GridCell key={cam.id} cam={cam} />
      ))}
    </div>
  );
}
