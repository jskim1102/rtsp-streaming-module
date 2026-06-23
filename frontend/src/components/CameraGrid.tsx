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

// 셀 = WhepPlayer(WebRTC). 카메라 식별 라벨 오버레이는 표시하지 않는다(스트리밍 화면 정리).
function GridCell({ cam, onFps }: { cam: Cam; onFps?: (streamKey: string, fps: number) => void }) {
  return (
    <div className="grid-cell">
      <WhepPlayer streamKey={cam.stream_key} onFps={(fps) => onFps?.(cam.stream_key, fps)} />
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
        // key 에 rtsp_url 포함 — 주소가 바뀌면 셀을 remount 해 WHEP 를 새 소스로 재연결한다
        // (수정 후 mediamtx 가 같은 stream_key 로 재등록되므로 streamKey-only effect 로는 갱신 안 됨).
        <GridCell key={`${cam.id}-${cam.rtsp_url}`} cam={cam} onFps={onFps} />
      ))}
    </div>
  );
}
