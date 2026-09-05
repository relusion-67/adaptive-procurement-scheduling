import { useCallback, useEffect, useState } from "react";
import { loadBookingContext } from "../core/bookingContext";
import { LIVE_REFRESH_INTERVAL_MS } from "../config";

const INITIAL_STATE = { bookingId: null, status: "loading", data: null, error: null };

// Mirrors the ACTIVE_STATUSES convention used elsewhere (e.g.
// schedulingAdapter.js, FarmerHome.jsx): only poll while the booking can
// still change state. Once it reaches a terminal status there is nothing
// left to refresh.
const POLLABLE_STATUSES = new Set(["BOOKED", "CHECKED_IN", "IN_QUEUE", "PROCESSING"]);

export function useBookingContext(bookingId) {
  const [state, setState] = useState(INITIAL_STATE);

  // silent: used by background polling so a single failed refresh doesn't
  // replace an already-visible Track screen with the full error state -
  // the manual "reload" (e.g. the retry button) still surfaces errors as
  // before.
  const load = useCallback(
    ({ silent = false } = {}) => {
      if (!bookingId) return;
      loadBookingContext(bookingId)
        .then((data) => setState({ bookingId, status: "ready", data, error: null }))
        .catch((error) => {
          if (silent) return;
          setState({ bookingId, status: "error", data: null, error });
        });
    },
    [bookingId],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Lightweight polling: periodically re-fetch so backend-driven changes
  // (queue movement, a centre going inactive, a new adaptive scheduling
  // assessment) surface without a manual reload. Plain setInterval, no
  // WebSockets, no new dependency, and the existing API contract (same
  // loadBookingContext call the initial load already uses) is unchanged.
  useEffect(() => {
    if (!bookingId) return undefined;
    if (!POLLABLE_STATUSES.has(state.data?.booking?.status)) return undefined;

    const intervalId = setInterval(() => {
      // Pause while the tab is hidden so a backgrounded phone/browser tab
      // doesn't keep polling the API for no visible benefit.
      if (document.visibilityState === "hidden") return;
      load({ silent: true });
    }, LIVE_REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [bookingId, state.data?.booking?.status, load]);

  // Derive the externally-visible status from whether the last completed
  // fetch matches the bookingId we were asked for, rather than resetting to
  // "loading" with a synchronous setState inside the effect above.
  const isCurrent = state.bookingId === bookingId;

  return {
    status: isCurrent ? state.status : "loading",
    data: isCurrent ? state.data : null,
    error: isCurrent ? state.error : null,
    reload: load,
  };
}
