export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

// Lightweight polling interval (ms) used by Track/Home so backend state
// changes (queue movement, adaptive scheduling updates) show up without a
// manual reload. Plain setInterval - no WebSockets, no new dependency.
export const LIVE_REFRESH_INTERVAL_MS = Number(
  import.meta.env.VITE_LIVE_REFRESH_INTERVAL_MS ?? 15000,
);
