import { TokenBadge } from "./TokenBadge";
import { IconUsers } from "./icons";

export function QueueStatus({ queueEntry, centreCode, farmersAhead }) {
  return (
    <div className="queue-status">
      <TokenBadge tokenNumber={queueEntry.token_number} centreCode={centreCode} />
      <div className="queue-status__ahead">
        <IconUsers aria-hidden="true" />
        <div>
          <span className="queue-status__ahead-value">{farmersAhead}</span>
          <span className="queue-status__ahead-label">
            {farmersAhead === 1 ? "farmer ahead of you" : "farmers ahead of you"}
          </span>
        </div>
      </div>
    </div>
  );
}
