import { IconAlertTriangle, IconRefresh } from "./icons";

export function LoadingState({ label = "Loading\u2026" }) {
  return (
    <div className="state-view state-view--loading" role="status" aria-live="polite">
      <span className="state-view__spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({
  message = "We couldn't load this. Please try again.",
  onRetry,
}) {
  return (
    <div className="state-view state-view--error" role="alert">
      <IconAlertTriangle className="state-view__icon" aria-hidden="true" />
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="btn btn--secondary" onClick={onRetry}>
          <IconRefresh aria-hidden="true" />
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, message, action }) {
  return (
    <div className="state-view state-view--empty">
      {title && <p className="state-view__title">{title}</p>}
      {message && <p>{message}</p>}
      {action}
    </div>
  );
}
