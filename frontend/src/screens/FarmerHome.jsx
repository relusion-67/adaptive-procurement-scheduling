import { useEffect, useState } from "react";
import { BookingSummary } from "../components/BookingSummary";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";
import { SCHEDULE_STATE_TONE } from "../components/statusTone";
import { IconChevronRight } from "../components/icons";
import { useSchedulingStatus } from "../hooks/useSchedulingStatus";
import { loadBookingContext } from "../core/bookingContext";
import { combineDateAndTime } from "../core/format";
import { addTrackedBookingId, getTrackedBookingIds } from "../core/storage";
import { navigate } from "../core/router";
import { SCHEDULE_STATE_LABELS } from "../core/statusLabels";
import { LIVE_REFRESH_INTERVAL_MS } from "../config";

const ACTIVE_STATUSES = new Set(["BOOKED", "CHECKED_IN", "IN_QUEUE", "PROCESSING"]);

export function FarmerHome({ farmer }) {
  const [state, setState] = useState({ status: "loading", context: null });
  const [trackInput, setTrackInput] = useState("");
  const [trackError, setTrackError] = useState(null);

  useEffect(() => {
    loadNextBooking(setState);
  }, []);

  // Lightweight polling so a booking that changes state elsewhere (checked
  // in from Track, moved through the queue, etc.) is reflected here without
  // a manual reload. Only worth polling once there's an active booking to
  // watch; same plain setInterval approach as useBookingContext, no new
  // dependency and no change to the existing loadNextBooking call.
  useEffect(() => {
    if (state.status !== "ready") return undefined;

    const intervalId = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      refreshNextBooking(setState, { silent: true });
    }, LIVE_REFRESH_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [state.status]);

  const { status: scheduleStatus } = useSchedulingStatus(
    state.status === "ready" ? state.context : null,
  );

  async function handleTrackExisting(event) {
    event.preventDefault();
    const bookingId = Number(trackInput);
    if (!bookingId) {
      setTrackError("Enter a valid booking ID.");
      return;
    }
    try {
      await loadBookingContext(bookingId);
      addTrackedBookingId(bookingId);
      navigate(`/track/${bookingId}`);
    } catch {
      setTrackError("We couldn't find that booking ID.");
    }
  }

  return (
    <div className="screen">
      <p className="screen__greeting">Welcome back, {farmer.name.split(" ")[0]}</p>

      {state.status === "loading" && <LoadingState label="Loading your procurement details\u2026" />}

      {state.status === "error" && (
        <ErrorState
          message="We couldn't load your procurement status. Please try again."
          onRetry={() => loadNextBooking(setState)}
        />
      )}

      {state.status === "empty" && (
        <EmptyState
          title="No active procurement booking"
          message="Book a procurement slot to get started."
          action={
            <button type="button" className="btn btn--primary" onClick={() => navigate("/book")}>
              Book a slot
            </button>
          }
        />
      )}

      {state.status === "ready" && (
        <>
          <h2 className="screen__section-title">Your next procurement</h2>
          <BookingSummary
            booking={state.context.booking}
            slot={state.context.slot}
            centre={state.context.centre}
          />

          {scheduleStatus && scheduleStatus.state !== "ON_TRACK" && (
            <button
              type="button"
              className="alert-pill"
              onClick={() => navigate(`/track/${state.context.booking.id}`)}
            >
              <StatusBadge
                label={SCHEDULE_STATE_LABELS[scheduleStatus.state]}
                tone={SCHEDULE_STATE_TONE[scheduleStatus.state]}
              />
              <span>See what changed</span>
              <IconChevronRight aria-hidden="true" />
            </button>
          )}

          <div className="screen__actions">
            <button
              type="button"
              className="btn btn--primary btn--block"
              onClick={() => navigate(`/track/${state.context.booking.id}`)}
            >
              Track procurement
            </button>
            <button
              type="button"
              className="btn btn--secondary btn--block"
              onClick={() => navigate("/book")}
            >
              Book a slot
            </button>
          </div>
        </>
      )}

      <details className="track-by-id">
        <summary>Track a booking using its ID</summary>
        <form className="track-by-id__form" onSubmit={handleTrackExisting}>
          <input
            type="number"
            min="1"
            placeholder="Booking ID"
            value={trackInput}
            onChange={(event) => {
              setTrackInput(event.target.value);
              setTrackError(null);
            }}
          />
          <button type="submit" className="btn btn--secondary">
            Track
          </button>
        </form>
        {trackError && <p className="form__error">{trackError}</p>}
      </details>
    </div>
  );
}

async function loadNextBooking(setState) {
  setState({ status: "loading", context: null });
  await refreshNextBooking(setState);
}

// Same fetch as loadNextBooking, but never resets to "loading" first, and -
// when called silently for background polling - never drops a
// currently-displayed booking to a hard error screen over a single failed
// refresh. Used so periodic polling doesn't flash the loading skeleton or
// bounce the farmer to an error state over a transient blip.
async function refreshNextBooking(setState, { silent = false } = {}) {
  const ids = getTrackedBookingIds();

  if (ids.length === 0) {
    setState({ status: "empty", context: null });
    return;
  }

  try {
    const results = await Promise.allSettled(ids.map((id) => loadBookingContext(id)));
    const contexts = results
      .filter((result) => result.status === "fulfilled")
      .map((result) => result.value);

    const active = contexts
      .filter((context) => ACTIVE_STATUSES.has(context.booking.status))
      .sort((a, b) => slotStart(a.slot) - slotStart(b.slot));

    if (active.length > 0) {
      setState({ status: "ready", context: active[0] });
      return;
    }

    setState({ status: "empty", context: null });
  } catch {
    if (!silent) setState({ status: "error", context: null });
  }
}

function slotStart(slot) {
  if (!slot) return Infinity;
  return combineDateAndTime(slot.slot_date, slot.start_time).getTime();
}
