import { useEffect, useRef, useState, useCallback } from "react";
import { wsBase } from "./useApi";

interface WsState {
  connected: boolean;
  imgSrc: string;
}

export function useWebSocket(path: string | null): WsState {
  const [connected, setConnected] = useState(false);
  const [imgSrc, setImgSrc] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const prevBlobRef = useRef("");

  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (prevBlobRef.current) {
      URL.revokeObjectURL(prevBlobRef.current);
      prevBlobRef.current = "";
    }
  }, []);

  useEffect(() => {
    if (!path) {
      cleanup();
      setConnected(false);
      setImgSrc("");
      return;
    }

    let reconnectTimer: ReturnType<typeof setTimeout>;
    let disposed = false;

    function connect() {
      if (disposed) return;
      const ws = new WebSocket(`${wsBase()}${path}`);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (ev) => {
        // binary JPEG only — 서버는 raw JPEG 프레임만 보낸다.
        if (ev.data instanceof ArrayBuffer) {
          const blob = new Blob([ev.data], { type: "image/jpeg" });
          const url = URL.createObjectURL(blob);
          if (prevBlobRef.current) URL.revokeObjectURL(prevBlobRef.current);
          prevBlobRef.current = url;
          setImgSrc(url);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        if (!disposed) reconnectTimer = setTimeout(connect, 2000);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      cleanup();
    };
  }, [path, cleanup]);

  return { connected, imgSrc };
}
