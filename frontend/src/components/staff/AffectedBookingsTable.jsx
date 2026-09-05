import { useState } from "react";
import { formatClockTime, parseIsoTimestamp, formatMinutes, toSafeNumber } from "../../core/format";
import { resolveCentreName } from "../../core/staffDashboardData";
import { RECOMMENDATION_LABELS, SCHEDULE_STATE_LABELS } from "../../core/statusLabels";
import { EmptyState } from "../StateViews";
import { StatusBadge } from "../StatusBadge";
import { SCHEDULE_STATE_TONE } from "../statusTone";
import { IconChevronRight } from "../icons";

/**
 * @param {object[]} affectedBookings - derived: assessments filtered to scheduling_status !== "ON_TRACK"
 * @param {object[]} centres - full centre list, used only to resolve recommended_centre_id -> name
 */
export function AffectedBookingsTable({ affectedBookings, centres }) {
  const [expandedId, setExpandedId] = useState(null);

  return (
    <section className="staff-panel" aria-label="Affected bookings">
      <h2 className="screen__section-title">Affected bookings</h2>

      {affectedBookings.length === 0 ? (
        <EmptyState title="Nothing to review" message="Every tracked booking is on track." />
      ) : (
        <ul className="staff-affected-list">
          {affectedBookings.map((assessment) => (
            <AffectedBookingRow
              key={assessment.booking_id}
              assessment={assessment}
              centres={centres}
              expanded={expandedId === assessment.booking_id}
              onToggle={() =>
                setExpandedId((current) =>
                  current === assessment.booking_id ? null : assessment.booking_id,
                )
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function AffectedBookingRow({ assessment, centres, expanded, onToggle }) {
  const completion = parseIsoTimestamp(assessment.estimated_completion_time);

  return (
    <li className="staff-affected-item">
      <button
        type="button"
        className="staff-affected-item__head"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="staff-affected-item__booking">Booking #{assessment.booking_id}</span>
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
          {assessment.recommended_centre_id != null && (
            <div>
              <dt>Recommended centre</dt>
              <dd>
                {resolveCentreName(centres, assessment.recommended_centre_id) ??
                  `Centre #${assessment.recommended_centre_id}`}
              </dd>
            </div>
          )}
          {assessment.recommended_slot_id != null && (
            <div>
              <dt>Recommended slot</dt>
              <dd>Slot #{assessment.recommended_slot_id}</dd>
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
}
