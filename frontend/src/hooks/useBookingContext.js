import { useCallback, useEffect, useRef, useState } from "react";
import { loadBookingContext } from "../core/bookingContext";
import { LIVE_REFRESH_INTERVAL_MS } from "../config";

const INITIAL_STATE = {
  bookingId: null,
  status: "loading",
  data: null,
  error: null,
};

const POLLABLE_STATUSES = new Set([
  "BOOKED",
  "CHECKED_IN",
  "IN_QUEUE",
  "PROCESSING",
]);

export function useBookingContext(bookingId) {
  const [state, setState] = useState(INITIAL_STATE);
  const requestIdRef = useRef(0);

  const load = useCallback(
    ({ silent = false } = {}) => {
      if (!bookingId) return;
      const requestId = ++requestIdRef.current;

      loadBookingContext(bookingId)
        .then((data) => {
          if (requestId !== requestIdRef.current) return;
          setState({
            bookingId,
            status: "ready",
            data,
            error: null,
          });
        })
        .catch((error) => {
          if (silent || requestId !== requestIdRef.current) return;

          setState({
            bookingId,
            status: "error",
            data: null,
            error,
          });
        });
    },
    [bookingId],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!bookingId) return undefined;

    if (!POLLABLE_STATUSES.has(state.data?.booking?.status)) {
      return undefined;
    }

    const intervalId = setInterval(() => {
      if (document.visibilityState === "hidden") return;

      load({ silent: true });
    }, LIVE_REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [bookingId, state.data?.booking?.status, load]);

  const isCurrent = state.bookingId === bookingId;

  return {
    status: isCurrent ? state.status : "loading",
    data: isCurrent ? state.data : null,
    error: isCurrent ? state.error : null,
    reload: load,
  };
}