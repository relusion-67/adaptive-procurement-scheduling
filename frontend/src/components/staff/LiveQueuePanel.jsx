import { QUEUE_STATUS_LABELS } from "../../core/statusLabels";
import { formatClockTime, parseIsoTimestamp } from "../../core/format";
import { EmptyState } from "../StateViews";
import { StatusBadge } from "../StatusBadge";
import { QUEUE_STATUS_TONE } from "../statusTone";

function formatTimestamp(value) {
  const date = parseIsoTimestamp(value);
  return date ? formatClockTime(date) : "\u2014";
}

/** @param {object[]} liveQueue - QueueEntryResponse[] from GET /api/queue/centres/{id} */
export function LiveQueuePanel({ liveQueue }) {
  return (
    <section className="staff-panel" aria-label="Live queue">
      <h2 className="screen__section-title">Live queue</h2>

      {liveQueue.length === 0 ? (
        <EmptyState
          title="Queue is empty"
          message="No farmers are currently waiting, called, or being served."
        />
      ) : (
        <div className="staff-table-wrap">
          <table className="staff-table">
            <thead>
              <tr>
                <th scope="col">Token</th>
                <th scope="col">Status</th>
                <th scope="col">Checked in</th>
                <th scope="col">Called</th>
                <th scope="col">Serving since</th>
              </tr>
            </thead>
            <tbody>
              {liveQueue.map((entry) => (
                <tr key={entry.id}>
                  <td>{String(entry.token_number).padStart(3, "0")}</td>
                  <td>
                    <StatusBadge
                      label={QUEUE_STATUS_LABELS[entry.queue_status]}
                      tone={QUEUE_STATUS_TONE[entry.queue_status]}
                    />
                  </td>
                  <td>{formatTimestamp(entry.checked_in_at)}</td>
                  <td>{formatTimestamp(entry.called_at)}</td>
                  <td>{formatTimestamp(entry.served_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
