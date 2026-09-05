// Small, dependency-free formatting helpers. Kept in one place so every
// screen renders dates/times/quantities the same way.

/** "2026-10-01" -> Date at local midnight (avoids UTC off-by-one). */
export function parseDate(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** "10:30:00" -> Date/time helper: combine a slot_date + time string. */
export function combineDateAndTime(isoDate, timeString) {
  const date = parseDate(isoDate);
  const [hours, minutes] = timeString.split(":").map(Number);
  date.setHours(hours, minutes, 0, 0);
  return date;
}

export function formatDate(isoDate) {
  const date = parseDate(isoDate);
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);

  if (isSameDay(date, today)) return "Today";
  if (isSameDay(date, tomorrow)) return "Tomorrow";

  return date.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** "10:30:00" -> "10:30 AM" */
export function formatTime(timeString) {
  const [hours, minutes] = timeString.split(":").map(Number);
  const date = new Date();
  date.setHours(hours, minutes, 0, 0);
  return date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

export function formatTimeRange(startTime, endTime) {
  return `${formatTime(startTime)} \u2013 ${formatTime(endTime)}`;
}

export function formatClockTime(date) {
  return date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

export function formatQuantity(quantityKg) {
  const value = Number(quantityKg);
  if (value >= 1000) return `${(value / 1000).toFixed(2)} tonnes`;
  return `${value.toLocaleString("en-IN")} kg`;
}

export function formatMinutes(minutes) {
  const rounded = Math.max(0, Math.round(Number(minutes)));
  if (rounded < 60) return `~${rounded} min`;
  const hours = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return remainder === 0 ? `~${hours} hr` : `~${hours} hr ${remainder} min`;
}

/**
 * The backend serializes Decimal fields (e.g. estimated_wait_minutes,
 * average_service_minutes) as JSON strings, not numbers, to avoid float
 * precision loss. Always route them through this before doing arithmetic.
 */
export function toSafeNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * The backend serializes datetimes as ISO 8601 strings with a UTC offset
 * (e.g. "2026-10-01T05:30:00+00:00"). `new Date(...)` parses that natively,
 * but returns an "Invalid Date" object (not null) on bad input, which
 * silently produces NaN in downstream math. This normalizes that to null.
 */
export function parseIsoTimestamp(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
