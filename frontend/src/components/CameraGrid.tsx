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
  // 카메라별 remount epoch(부모가 RTSP 변경 편집마다 bump) — GridCell key 에 넣어 셀 remount 트리거.
  epochs?: Record<number, number>;
}

// 셀 = WhepPlayer(WebRTC). 카메라 식별 라벨 오버레이는 표시하지 않는다(스트리밍 화면 정리).
function GridCell({ cam, onFps }: { cam: Cam; onFps?: (streamKey: string, fps: number) => void }) {
  return (
    <div className="grid-cell">
      <WhepPlayer streamKey={cam.stream_key} onFps={(fps) => onFps?.(cam.stream_key, fps)} />
    </div>
  );
}

export default function CameraGrid({ cams, onFps, epochs }: Props) {
  if (cams.length === 0) {
    return <p className="grid-empty">등록된 카메라가 없습니다.</p>;
  }

  const columns = getGridColumns(cams.length);

  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
      {cams.map((cam) => (
        // key 에 epoch 포함 — 부모가 RTSP 변경 편집 시 bump → 셀 remount → WHEP 재연결.
        // (응답 rtsp_url 은 마스킹이라 비번-only 변경을 못 잡아 key 재료로 부족하다.)
        <GridCell key={`${cam.id}-${epochs?.[cam.id] ?? 0}`} cam={cam} onFps={onFps} />
      ))}
    </div>
  );
}
