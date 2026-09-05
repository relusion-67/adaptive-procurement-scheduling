// Maps every backend/technical status code to the farmer-facing language
// defined in the product brief. Nothing in a screen component should print
// a raw enum value - it should look it up here instead.

export const BOOKING_STATUS_LABELS = {
  BOOKED: "Booking confirmed",
  CHECKED_IN: "Checked in",
  IN_QUEUE: "Waiting at centre",
  PROCESSING: "Procurement in progress",
  COMPLETED: "Completed",
  MISSED: "Missed procurement",
  CANCELLED: "Booking cancelled",
};

export const QUEUE_STATUS_LABELS = {
  WAITING: "Waiting at centre",
  CALLED: "Your turn is next",
  SERVING: "Procurement in progress",
  DONE: "Completed",
  NO_SHOW: "Missed procurement",
};

export const SCHEDULE_STATE_LABELS = {
  ON_TRACK: "On track",
  AT_RISK: "May be delayed",
  DELAYED: "Delayed",
};

export const SCHEDULE_STATE_HEADLINES = {
  ON_TRACK: "Your procurement slot is on track.",
  AT_RISK: "Your procurement may take longer than expected.",
  DELAYED: "Your procurement slot may be delayed.",
};

export const RECOMMENDATION_LABELS = {
  KEEP_SLOT: "Keep current slot",
  WARN_FARMER: "Expect delay",
  PROPOSE_NEW_SLOT: "New slot recommended",
  RECOMMEND_ALTERNATE_CENTRE: "Alternative centre recommended",
};

// A single ordered list drives the visual timeline on the Track Procurement
// screen. `matches` decides which steps are already complete given a
// booking's current status.
export const TIMELINE_STEPS = [
  { key: "BOOKED", label: "Booking confirmed" },
  { key: "CHECKED_IN", label: "Checked in" },
  { key: "IN_QUEUE", label: "Waiting" },
  { key: "CALLED", label: "Your turn" },
  { key: "PROCESSING", label: "Processing" },
  { key: "COMPLETED", label: "Completed" },
];

const TIMELINE_ORDER = TIMELINE_STEPS.map((step) => step.key);

/**
 * Resolves how far along the timeline a booking + (optional) queue entry
 * has progressed, accounting for the fact that "your turn" (CALLED) is a
 * queue-level state that doesn't have its own BookingStatus value.
 */
export function currentTimelineIndex(bookingStatus, queueStatus) {
  if (bookingStatus === "MISSED" || bookingStatus === "CANCELLED") {
    return -1;
  }
  if (queueStatus === "CALLED" || queueStatus === "SERVING") {
    return TIMELINE_ORDER.indexOf(queueStatus === "SERVING" ? "PROCESSING" : "CALLED");
  }
  return TIMELINE_ORDER.indexOf(bookingStatus);
}
