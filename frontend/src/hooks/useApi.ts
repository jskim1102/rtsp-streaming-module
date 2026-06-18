const API_PORT = import.meta.env.VITE_API_PORT || "8000";
const WEBRTC_PORT = import.meta.env.VITE_MEDIAMTX_WEBRTC_PORT || "8893";

export function apiBase(): string {
  return `http://${window.location.hostname}:${API_PORT}`;
}

// mediamtx WHEP endpoint base — 브라우저가 mediamtx 에 직접 접속(백엔드 경유 X).
export function whepBase(): string {
  return `http://${window.location.hostname}:${WEBRTC_PORT}`;
}
