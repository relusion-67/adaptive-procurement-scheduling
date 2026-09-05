import { IconTicket } from "./icons";

export function TokenBadge({ tokenNumber, centreCode }) {
  return (
    <div className="token-badge">
      <IconTicket className="token-badge__icon" aria-hidden="true" />
      <div>
        <span className="token-badge__label">Your token</span>
        <span className="token-badge__value">
          {centreCode ? `${centreCode.split("-")[0]}-` : ""}
          {String(tokenNumber).padStart(3, "0")}
        </span>
      </div>
    </div>
  );
}
