import { useState } from "react";
import { ApiError } from "../../api/client";
import { recalculateThroughput } from "../../api/endpoints";
import { formatClockTime, formatMinutes, toSafeNumber } from "../../core/format";
import { IconRefresh, IconSignal } from "../icons";

/**
 * @param {object} centre - ProcurementCentreResponse
 * @param {object} throughput - { status: "available"|"unavailable", snapshot }
 * @param {number} liveQueueCount - derived: liveQueue.length
 * @param {number} pendingBookingsCount - derived: assessments.length
 * @param {() => void} onThroughputRecalculated
 */
export function CentreHealthPanel({
  centre,
  throughput,
  liveQueueCount,
  pendingBookingsCount,
  onThroughputRecalculated,
}) {
  const [recalculating, setRecalculating] = useState(false);
  const [recalcError, setRecalcError] = useState(null);

  if (!centre) return null;

  async function handleRecalculate() {
    setRecalculating(true);
    setRecalcError(null);
    try {
      await recalculateThroughput(centre.id);
      onThroughputRecalculated?.();
    } catch (error) {
      setRecalcError(
        error instanceof ApiError && error.status === 409
          ? "Not enough completed queue history yet to recalculate."
          : "Couldn't recalculate throughput. Please try again.",
      );
    } finally {
      setRecalculating(false);
    }
  }

  return (
    <section className="staff-panel" aria-label="Centre health">
      <div className="staff-panel__head">
        <div>
          <h2 className="screen__section-title">{centre.name}</h2>
          <p className="staff-panel__subtitle">
            {centre.code} {"\u00b7"} {centre.district} district
          </p>
        </div>
        <IconSignal aria-hidden="true" className="staff-panel__head-icon" />
      </div>

      <dl className="staff-stat-grid">
        <div className="staff-stat">
          <dt>Daily capacity</dt>
          <dd>{centre.daily_capacity} farmers/day</dd>
          <p className="staff-stat__note">From the centre record.</p>
        </div>

        <div className="staff-stat">
          <dt>In live queue now</dt>
          <dd>{liveQueueCount}</dd>
          <p className="staff-stat__note">Waiting, called, or being served.</p>
        </div>

        <div className="staff-stat">
          <dt>Bookings tracked</dt>
          <dd>{pendingBookingsCount}</dd>
          <p className="staff-stat__note">
            Derived {"\u2014"} not-yet-completed bookings the scheduler is currently assessing.
          </p>
        </div>

        <div className="staff-stat">
          <dt>Service pace</dt>
          {throughput.status === "available" ? (
            <>
              <dd>{formatMinutes(toSafeNumber(throughput.snapshot.avg_minutes_per_farmer))} / farmer</dd>
              <p className="staff-stat__note">
                Last measured {formatClockTime(new Date(throughput.snapshot.snapshot_at))}.
              </p>
            </>
          ) : (
            <>
              <dd>{"\u2014"}</dd>
              <p className="staff-stat__note">Not enough completed service history yet.</p>
            </>
          )}
        </div>
      </dl>

      <button
        type="button"
        className="btn btn--secondary btn--block"
        onClick={handleRecalculate}
        disabled={recalculating}
      >
        <IconRefresh aria-hidden="true" />
        {recalculating ? "Recalculating\u2026" : "Recalculate throughput"}
      </button>
      {recalcError && <p className="form__error">{recalcError}</p>}
    </section>
  );
}
