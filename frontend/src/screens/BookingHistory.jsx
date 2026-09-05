import { useEffect, useState } from "react";
import { BookingSummary } from "../components/BookingSummary";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { loadBookingContext } from "../core/bookingContext";
import { getTrackedBookingIds } from "../core/storage";
import { navigate } from "../core/router";

export function BookingHistory() {
  const [state, setState] = useState({ status: "loading", items: [] });

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setState({ status: "loading", items: [] });
    const ids = getTrackedBookingIds();
    if (ids.length === 0) {
      setState({ status: "empty", items: [] });
      return;
    }
    try {
      const results = await Promise.allSettled(ids.map((id) => loadBookingContext(id)));
      const items = results
        .filter((result) => result.status === "fulfilled")
        .map((result) => result.value)
        .sort((a, b) => b.booking.id - a.booking.id);
      setState({ status: items.length ? "ready" : "empty", items });
    } catch {
      setState({ status: "error", items: [] });
    }
  }

  return (
    <div className="screen">
      <h2 className="screen__section-title">Booking history</h2>

      {state.status === "loading" && <LoadingState label="Loading your bookings\u2026" />}
      {state.status === "error" && <ErrorState onRetry={load} />}
      {state.status === "empty" && (
        <EmptyState
          title="No bookings yet"
          message="Bookings you make on this phone will show up here."
        />
      )}

      {state.status === "ready" && (
        <div className="history-list">
          {state.items.map(({ booking, slot, centre }) => (
            <button
              key={booking.id}
              type="button"
              className="history-list__item"
              onClick={() => navigate(`/track/${booking.id}`)}
            >
              <BookingSummary booking={booking} slot={slot} centre={centre} compact />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
