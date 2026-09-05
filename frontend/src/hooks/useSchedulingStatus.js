import { useEffect, useState } from "react";
import { getSchedulingStatus } from "../core/schedulingAdapter";

const INITIAL_STATE = { context: null, status: null };

/** @param {object|null} context - the object returned by loadBookingContext */
export function useSchedulingStatus(context) {
  const [state, setState] = useState(INITIAL_STATE);

  useEffect(() => {
    if (!context?.booking || !context?.slot || !context?.centre) {
      return undefined;
    }
    let cancelled = false;
    getSchedulingStatus(context)
      .then((result) => {
        if (!cancelled) setState({ context, status: result });
      })
      .catch(() => {
        if (!cancelled) setState({ context, status: null });
      });
    return () => {
      cancelled = true;
    };
  }, [context]);

  // Derived, rather than reset synchronously in the effect above: "loading"
  // is simply "we have enough data to ask, but haven't heard back for this
  // exact context object yet".
  const isCurrent = state.context === context;
  const hasEnoughData = Boolean(context?.booking && context?.slot && context?.centre);

  return {
    status: isCurrent ? state.status : null,
    loading: hasEnoughData && !isCurrent,
  };
}
