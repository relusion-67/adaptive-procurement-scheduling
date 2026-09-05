import { BookingSummary } from "../components/BookingSummary";
import { ErrorState, LoadingState } from "../components/StateViews";
import { IconCheckCircle } from "../components/icons";
import { useBookingContext } from "../hooks/useBookingContext";
import { navigate } from "../core/router";

export function BookingConfirmation({ bookingId }) {
  const { status, data, reload } = useBookingContext(bookingId);

  return (
    <div className="screen">
      {status === "loading" && <LoadingState label="Confirming your booking\u2026" />}

      {status === "error" && (
        <ErrorState
          message="We couldn't load your booking confirmation. Please try again."
          onRetry={reload}
        />
      )}

      {status === "ready" && (
        <>
          <div className="confirmation-banner">
            <IconCheckCircle aria-hidden="true" />
            <div>
              <p className="confirmation-banner__title">Booking confirmed</p>
              <p className="confirmation-banner__id">Booking ID: {data.booking.id}</p>
            </div>
          </div>

          <BookingSummary booking={data.booking} slot={data.slot} centre={data.centre} />

          <div className="screen__actions">
            <button
              type="button"
              className="btn btn--primary btn--block"
              onClick={() => navigate(`/track/${data.booking.id}`)}
            >
              Track my procurement
            </button>
            <button type="button" className="btn btn--secondary btn--block" onClick={() => navigate("/")}>
              Back to home
            </button>
          </div>
        </>
      )}
    </div>
  );
}
