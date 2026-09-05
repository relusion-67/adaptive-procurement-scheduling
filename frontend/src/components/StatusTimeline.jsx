import { currentTimelineIndex, TIMELINE_STEPS } from "../core/statusLabels";
import { IconCheckCircle } from "./icons";

export function StatusTimeline({ bookingStatus, queueStatus }) {
  const currentIndex = currentTimelineIndex(bookingStatus, queueStatus);
  const isStopped = bookingStatus === "MISSED" || bookingStatus === "CANCELLED";

  return (
    <ol className="timeline" aria-label="Procurement progress">
      {TIMELINE_STEPS.map((step, index) => {
        const state = isStopped
          ? "pending"
          : index < currentIndex
            ? "done"
            : index === currentIndex
              ? "current"
              : "pending";
        return (
          <li key={step.key} className={`timeline__step timeline__step--${state}`}>
            <span className="timeline__marker" aria-hidden="true">
              {state === "done" ? <IconCheckCircle /> : <span className="timeline__dot" />}
            </span>
            <span className="timeline__label">{step.label}</span>
          </li>
        );
      })}
      {isStopped && (
        <li className="timeline__step timeline__step--stopped">
          <span className="timeline__marker" aria-hidden="true">
            <span className="timeline__dot" />
          </span>
          <span className="timeline__label">
            {bookingStatus === "MISSED" ? "Missed procurement" : "Booking cancelled"}
          </span>
        </li>
      )}
    </ol>
  );
}
