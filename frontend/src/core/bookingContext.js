// Combines several existing endpoints into the one bundle every screen
// actually needs to render a booking: the booking itself, its centre and
// slot, and - if the farmer has checked in - their live queue entry + ETA.
//
// NOTE ON A BACKEND GAP: there is no GET /api/centres/{id} (single) or
// GET /api/queue/bookings/{booking_id} endpoint today, only
// GET /api/centres/ (list) and GET /api/queue/centres/{centre_id} (live
// queue for a centre). This loader works around both by fetching the list
// and filtering client-side, which is fine at demo scale but is exactly
// the kind of thing a real GET /api/farmers/{id}/bookings +
// GET /api/bookings/{id}/queue-entry pair would simplify. Flagged in the
// final report rather than changed here, since backend changes are out of
// scope for this workstream.
import { getBooking, getLiveQueue, getQueueEta, getSlot, listCentres } from "../api/endpoints";

const LIVE_QUEUE_BOOKING_STATUSES = new Set(["CHECKED_IN", "IN_QUEUE", "PROCESSING"]);

/**
 * @param {number} bookingId
 */
export async function loadBookingContext(bookingId) {
  const booking = await getBooking(bookingId);
  const centres = await listCentres();
  const centre = centres.find((c) => c.id === booking.centre_id) ?? null;

  // Fetch the booking's slot directly by id via GET /api/slots/{slot_id},
  // which (unlike the centre's "usable slots" listing) returns the slot
  // regardless of remaining capacity. This keeps a booking's date/time and
  // adaptive status visible even after the slot fills up to capacity 0.
  let slot = null;
  try {
    slot = await getSlot(booking.slot_id);
  } catch {
    slot = null;
  }

  let queueEntry = null;
  let eta = null;
  if (centre && LIVE_QUEUE_BOOKING_STATUSES.has(booking.status)) {
    try {
      const liveQueue = await getLiveQueue(centre.id);
      queueEntry = liveQueue.find((entry) => entry.booking_id === booking.id) ?? null;
      if (queueEntry) {
        eta = await getQueueEta(queueEntry.id).catch(() => null);
        if (eta) {
          // Computed once, here, at fetch time - not during render - so
          // components can read a stable timestamp instead of calling
          // Date.now() themselves on every render.
          eta.estimatedCompletionAt = new Date(
            Date.now() + Number(eta.estimated_wait_minutes) * 60000,
          );
        }
      }
    } catch {
      queueEntry = null;
    }
  }

  return { booking, centre, slot, queueEntry, eta };
}
