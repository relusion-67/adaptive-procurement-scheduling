import { useState } from "react";
import { callNextFarmer, completeService, markNoShow, startServing } from "../../api/endpoints";
import { QUEUE_STATUS_LABELS } from "../../core/statusLabels";
import { EmptyState } from "../StateViews";
import { StatusBadge } from "../StatusBadge";
import { TokenBadge } from "../TokenBadge";
import { QUEUE_STATUS_TONE } from "../statusTone";
import { IconUsers } from "../icons";

/**
 * @param {number} centreId
 * @param {object|null} currentlyServing - the live queue entry with queue_status === "SERVING", if any
 * @param {object|null} currentlyCalled - the live queue entry with queue_status === "CALLED", if any
 * @param {number} waitingCount - derived count of WAITING entries
 * @param {() => void} onActionDone - called after any queue action succeeds, to trigger a reload
 */
export function CurrentlyServingPanel({
  centreId,
  currentlyServing,
  currentlyCalled,
  waitingCount,
  onActionDone,
}) {
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

  async function run(action) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      onActionDone?.();
    } catch {
      setActionError("That action didn't go through. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const canCallNext = !currentlyCalled && waitingCount > 0;

  return (
    <section className="staff-panel" aria-label="Currently serving">
      <h2 className="screen__section-title">Currently serving</h2>

      {currentlyServing ? (
        <div className="staff-serving">
          <TokenBadge tokenNumber={currentlyServing.token_number} />
          <StatusBadge label={QUEUE_STATUS_LABELS.SERVING} tone={QUEUE_STATUS_TONE.SERVING} />
          <div className="staff-serving__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy}
              onClick={() => run(() => completeService(currentlyServing.id))}
            >
              Mark complete
            </button>
          </div>
        </div>
      ) : currentlyCalled ? (
        <div className="staff-serving">
          <TokenBadge tokenNumber={currentlyCalled.token_number} />
          <StatusBadge label={QUEUE_STATUS_LABELS.CALLED} tone={QUEUE_STATUS_TONE.CALLED} />
          <div className="staff-serving__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy}
              onClick={() => run(() => startServing(currentlyCalled.id))}
            >
              Start serving
            </button>
            <button
              type="button"
              className="btn btn--secondary"
              disabled={busy}
              onClick={() => run(() => markNoShow(currentlyCalled.id))}
            >
              Mark no-show
            </button>
          </div>
        </div>
      ) : (
        <EmptyState
          title="No one called yet"
          message={
            waitingCount > 0
              ? `${waitingCount} farmer${waitingCount === 1 ? "" : "s"} waiting in the queue.`
              : "The live queue is empty."
          }
        />
      )}

      <button
        type="button"
        className="btn btn--secondary btn--block"
        disabled={busy || !canCallNext}
        onClick={() => run(() => callNextFarmer(centreId))}
      >
        <IconUsers aria-hidden="true" />
        Call next farmer
      </button>
      {actionError && <p className="form__error">{actionError}</p>}
    </section>
  );
}
