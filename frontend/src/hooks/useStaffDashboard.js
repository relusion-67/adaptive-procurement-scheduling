import { useCallback, useEffect, useRef, useState } from "react";
import { loadStaffDashboard } from "../core/staffDashboardData";

// Staff need near-live data (queue/throughput can change every few
// seconds), so this polls in the background rather than requiring a
// manual refresh like the farmer screens do.
const POLL_INTERVAL_MS = 8000;

const INITIAL_STATE = { centreId: null, status: "idle", data: null, error: null };

/**
 * Loads (and polls) the staff dashboard aggregation for one centre.
 * Background refreshes are silent - they keep whatever is currently on
 * screen instead of flashing back to a loading state; only the first load
 * for a given centre (or an explicit reload()) shows the loading state.
 */
export function useStaffDashboard(centreId) {
  const [state, setState] = useState(INITIAL_STATE);
  const intervalRef = useRef(null);

  const load = useCallback(
    (isBackground) => {
      if (!centreId) return;
      // No synchronous setState here on purpose (mirrors
      // hooks/useBookingContext.js): "loading" is derived below from
      // whether the last completed fetch matches the requested centreId,
      // rather than reset eagerly inside the effect.
      loadStaffDashboard(centreId)
        .then((data) => setState({ centreId, status: "ready", data, error: null }))
        .catch((error) =>
          setState((prev) => ({
            centreId,
            status: "error",
            // Keep the last-known-good data visible behind the error on a
            // failed background refresh, rather than blanking the screen.
            data: isBackground ? prev.data : null,
            error,
          })),
        );
    },
    [centreId],
  );

  useEffect(() => {
    if (!centreId) return undefined;
    load(false);
    intervalRef.current = setInterval(() => load(true), POLL_INTERVAL_MS);
    return () => clearInterval(intervalRef.current);
  }, [centreId, load]);

  // Derived, not reset synchronously: while a fetch for a newly-selected
  // centre is in flight, state still reflects the previous centre.
  const isCurrent = state.centreId === centreId;

  return {
    status: isCurrent ? state.status : "loading",
    data: isCurrent ? state.data : null,
    error: isCurrent ? state.error : null,
    reload: () => load(false),
  };
}
