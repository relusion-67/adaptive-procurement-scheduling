// Tone lookup tables for StatusBadge, kept in a plain module (not the
// component file) so React Fast Refresh can keep working during dev -
// files that mix component exports with plain constants opt out of it.
export const BOOKING_STATUS_TONE = {
  BOOKED: "neutral",
  CHECKED_IN: "neutral",
  IN_QUEUE: "neutral",
  PROCESSING: "good",
  COMPLETED: "good",
  MISSED: "danger",
  CANCELLED: "danger",
};

export const SCHEDULE_STATE_TONE = {
  ON_TRACK: "good",
  AT_RISK: "warning",
  DELAYED: "danger",
};

// Used by the staff dashboard's live queue table and currently-serving
// panel (the farmer app never renders a raw QueueStatus badge).
export const QUEUE_STATUS_TONE = {
  WAITING: "neutral",
  CALLED: "warning",
  SERVING: "good",
  DONE: "good",
  NO_SHOW: "danger",
};
