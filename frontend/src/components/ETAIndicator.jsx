import { formatClockTime, formatMinutes } from "../core/format";
import { IconClock } from "./icons";

export function ETAIndicator({ estimatedWaitMinutes, estimatedCompletion }) {
  return (
    <div className="eta-indicator">
      <IconClock aria-hidden="true" />
      <div>
        <span className="eta-indicator__wait">
          Estimated wait: {formatMinutes(estimatedWaitMinutes)}
        </span>
        {estimatedCompletion && (
          <span className="eta-indicator__completion">
            Likely done by {formatClockTime(estimatedCompletion)}
          </span>
        )}
      </div>
    </div>
  );
}
