import { formatClockTime, formatDate, formatTimeRange } from "../core/format";
import { SCHEDULE_STATE_HEADLINES, SCHEDULE_STATE_LABELS } from "../core/statusLabels";
import { StatusBadge } from "./StatusBadge";
import { SCHEDULE_STATE_TONE } from "./statusTone";
import { IconCheckCircle } from "./icons";

/**
 * @param {object} status - the object returned by getSchedulingStatus()
 * @param {(recommendation: object) => void} onReviewRecommendation - called
 *   when the farmer taps to look at a suggested new slot/centre. Never
 *   applies anything automatically - the farmer always makes the final call.
 */
export function SchedulingAlert({ status, onReviewRecommendation }) {
  if (!status) return null;

  const { state, scheduledSlot, estimatedCompletion, reason, recommendation } = status;
  const isOnTrack = state === "ON_TRACK";

  return (
    <section
      className={`scheduling-alert scheduling-alert--${state.toLowerCase()}`}
      aria-live="polite"
    >
      <div className="scheduling-alert__head">
        <StatusBadge label={SCHEDULE_STATE_LABELS[state]} tone={SCHEDULE_STATE_TONE[state]} />
      </div>

      <p className="scheduling-alert__headline">{SCHEDULE_STATE_HEADLINES[state]}</p>

      {reason && <p className="scheduling-alert__reason">{reason}</p>}

      <dl className="scheduling-alert__details">
        {scheduledSlot && (
          <div>
            <dt>Current slot</dt>
            <dd>{formatTimeRange(scheduledSlot.start_time, scheduledSlot.end_time)}</dd>
          </div>
        )}
        {estimatedCompletion && (
          <div>
            <dt>Estimated completion</dt>
            <dd>{formatClockTime(estimatedCompletion)}</dd>
          </div>
        )}
      </dl>

      {isOnTrack ? (
        <p className="scheduling-alert__keep">
          <IconCheckCircle aria-hidden="true" />
          Keep your current slot {"\u2014"} no action needed.
        </p>
      ) : (
        <RecommendationPanel
          recommendation={recommendation}
          onReview={onReviewRecommendation}
        />
      )}
    </section>
  );
}

function RecommendationPanel({ recommendation, onReview }) {
  if (!recommendation || recommendation.type === "WARN_FARMER") {
    return (
      <p className="scheduling-alert__note">
        We're watching your centre closely and will let you know as soon as a
        better option is available.
      </p>
    );
  }

  if (recommendation.type === "PROPOSE_NEW_SLOT") {
    const { slot } = recommendation;
    return (
      <div className="scheduling-alert__recommendation">
        <p className="scheduling-alert__recommendation-eyebrow">Recommended</p>
        <p className="scheduling-alert__recommendation-slot">
          {formatDate(slot.slot_date)}, {formatTimeRange(slot.start_time, slot.end_time)}
        </p>
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => onReview?.(recommendation)}
        >
          Review new slot
        </button>
        <p className="scheduling-alert__disclaimer">
          Your current booking stays as-is until you confirm a change.
        </p>
      </div>
    );
  }

  if (recommendation.type === "RECOMMEND_ALTERNATE_CENTRE") {
    const { slot, centre } = recommendation;
    return (
      <div className="scheduling-alert__recommendation">
        <p className="scheduling-alert__recommendation-eyebrow">Alternative centre</p>
        <p className="scheduling-alert__recommendation-slot">{centre.name}</p>
        <p className="scheduling-alert__recommendation-slot scheduling-alert__recommendation-slot--muted">
          {formatDate(slot.slot_date)}, {formatTimeRange(slot.start_time, slot.end_time)}
        </p>
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => onReview?.(recommendation)}
        >
          Review alternative
        </button>
        <p className="scheduling-alert__disclaimer">
          Your current booking stays as-is until you confirm a change.
        </p>
      </div>
    );
  }

  return null;
}
