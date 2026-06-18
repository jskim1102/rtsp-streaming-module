const API_PORT = import.meta.env.VITE_API_PORT || "8000";

export function apiBase(): string {
  return `http://${window.location.hostname}:${API_PORT}`;
}

export function wsBase(): string {
  return `ws://${window.location.hostname}:${API_PORT}`;
}
