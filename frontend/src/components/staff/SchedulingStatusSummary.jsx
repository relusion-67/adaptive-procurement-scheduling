import { SCHEDULING_STATES } from "../../core/staffDashboardData";
import { SCHEDULE_STATE_LABELS } from "../../core/statusLabels";
import { StatusBadge } from "../StatusBadge";
import { SCHEDULE_STATE_TONE } from "../statusTone";

/**
 * @param {{ON_TRACK: number, AT_RISK: number, DELAYED: number}} statusCounts - derived client-side, see core/staffDashboardData.js
 * @param {number} totalTracked - assessments.length
 */
export function SchedulingStatusSummary({ statusCounts, totalTracked }) {
  return (
    <section className="staff-panel" aria-label="Scheduling status summary">
      <h2 className="screen__section-title">Booking status</h2>
      <p className="staff-panel__subtitle">
        Derived {"\u2014"} counted from {totalTracked} booking{totalTracked === 1 ? "" : "s"}{" "}
        currently assessed by the scheduler.
      </p>

      <div className="staff-status-summary">
        {SCHEDULING_STATES.map((state) => (
          <div className="staff-status-summary__item" key={state}>
            <StatusBadge label={SCHEDULE_STATE_LABELS[state]} tone={SCHEDULE_STATE_TONE[state]} />
            <span className="staff-status-summary__count">{statusCounts[state]}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
