import type { Cam } from "../pages/CamerasPage";
import WhepPlayer from "./WhepPlayer";

// 사용자 오버라이드(게이트2) — 1줄 최대 4칸, 4 채워지면 다음 줄로 wrap.
// (이전: deepeye-pose 추출 ≤1→1/≤2→2/≤4→2/≤9→3/else→4. spec Decisions 동기화 필요.)
function getGridColumns(count: number): number {
  return Math.min(Math.max(count, 1), 4);
}

interface Props {
  cams: Cam[];
  onFps?: (streamKey: string, fps: number) => void;
}

// 셀 = WhepPlayer(WebRTC) + 카메라 이름 오버레이.
function GridCell({ cam, onFps }: { cam: Cam; onFps?: (streamKey: string, fps: number) => void }) {
  return (
    <div className="grid-cell">
      <WhepPlayer streamKey={cam.stream_key} onFps={(fps) => onFps?.(cam.stream_key, fps)} />
      <span className="grid-cell-name">{cam.name}</span>
    </div>
  );
}

export default function CameraGrid({ cams, onFps }: Props) {
  if (cams.length === 0) {
    return <p className="grid-empty">등록된 카메라가 없습니다.</p>;
  }

  const columns = getGridColumns(cams.length);

  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
      {cams.map((cam) => (
        <GridCell key={cam.id} cam={cam} onFps={onFps} />
      ))}
    </div>
  );
}
