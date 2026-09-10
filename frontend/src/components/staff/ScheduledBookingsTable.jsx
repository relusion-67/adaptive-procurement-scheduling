import { useState } from "react";
import {
  formatClockTime,
  formatDate,
  formatMinutes,
  formatTimeRange,
  parseIsoTimestamp,
  toSafeNumber,
} from "../../core/format";
import { RECOMMENDATION_LABELS, SCHEDULE_STATE_LABELS } from "../../core/statusLabels";
import { EmptyState } from "../StateViews";
import { StatusBadge } from "../StatusBadge";
import { SCHEDULE_STATE_TONE } from "../statusTone";
import { IconChevronRight } from "../icons";

/**
 * @param {object[]} bookings - scheduling assessments for all pending bookings
 */
export function ScheduledBookingsTable({ bookings }) {
  const [expandedId, setExpandedId] = useState(null);

  return (
    <section className="staff-panel" aria-label="Scheduled bookings">
      <h2 className="screen__section-title">Scheduled bookings</h2>
      <p className="staff-panel__subtitle">
        Booked farmers tracked by the scheduler. They appear in the live queue after check-in.
      </p>

      {bookings.length === 0 ? (
        <EmptyState title="No scheduled bookings" message="There are no pending bookings for this centre." />
      ) : (
        <ul className="staff-affected-list">
          {bookings.map((assessment) => {
            const expanded = expandedId === assessment.booking_id;
            const completion = parseIsoTimestamp(assessment.estimated_completion_time);
            return (
              <li className="staff-affected-item" key={assessment.booking_id}>
                <button
                  type="button"
                  className="staff-affected-item__head"
                  onClick={() =>
                    setExpandedId((current) =>
                      current === assessment.booking_id ? null : assessment.booking_id,
                    )
                  }
                  aria-expanded={expanded}
                >
                  <span className="staff-affected-item__booking">
                    Booking #{assessment.booking_id}
                  </span>
                  <StatusBadge
                    label={SCHEDULE_STATE_LABELS[assessment.scheduling_status]}
                    tone={SCHEDULE_STATE_TONE[assessment.scheduling_status]}
                  />
                  <IconChevronRight
                    aria-hidden="true"
                    className={`staff-affected-item__chevron ${
                      expanded ? "staff-affected-item__chevron--open" : ""
                    }`}
                  />
                </button>
                {assessment.slot && (
                  <p className="staff-affected-item__recommendation">
                    {formatDate(assessment.slot.slot_date)} {"\u00b7"}{" "}
                    {formatTimeRange(assessment.slot.start_time, assessment.slot.end_time)}
                  </p>
                )}
                <p className="staff-affected-item__recommendation">
                  Recommendation: {RECOMMENDATION_LABELS[assessment.recommendation]}
                </p>
                {expanded && (
                  <dl className="staff-affected-item__details">
                    <div>
                      <dt>Farmers ahead</dt>
                      <dd>{assessment.farmers_ahead}</dd>
                    </div>
                    <div>
                      <dt>Estimated wait</dt>
                      <dd>{formatMinutes(toSafeNumber(assessment.estimated_wait_minutes))}</dd>
                    </div>
                    {completion && (
                      <div>
                        <dt>Estimated completion</dt>
                        <dd>{formatClockTime(completion)}</dd>
                      </div>
                    )}
                    <div className="staff-affected-item__explanation">
                      <dt>Scheduler notes</dt>
                      <dd>{assessment.explanation}</dd>
                    </div>
                  </dl>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
