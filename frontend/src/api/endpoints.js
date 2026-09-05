// Thin, named wrappers around the shared API client (client.js).
// Screens and hooks call these instead of building URL strings inline, so
// the request shape for each backend resource lives in exactly one place.
import { getJson, postJson } from "./client";

// ---- Farmers ---------------------------------------------------------

export function createFarmer({ name, phone, village }) {
  return postJson("/api/farmers/", { name, phone, village });
}

export function listFarmers() {
  return getJson("/api/farmers/");
}

// ---- Procurement centres & slots --------------------------------------

export function listCentres() {
  return getJson("/api/centres/");
}

export function listCentreSlots(centreId) {
  return getJson(`/api/centres/${centreId}/slots`);
}

// Direct lookup by slot id. Unlike listCentreSlots() (which intentionally
// excludes full/expired slots for NEW booking discovery), this returns the
// slot regardless of remaining capacity, so an *existing* booking can still
// retrieve its slot's date/time after the slot fills up.
export function getSlot(slotId) {
  return getJson(`/api/slots/${slotId}`);
}

// ---- Bookings ----------------------------------------------------------

export function createBooking({ farmerId, centreId, slotId, cropType, quantityKg }) {
  return postJson("/api/bookings/", {
    farmer_id: farmerId,
    centre_id: centreId,
    slot_id: slotId,
    crop_type: cropType,
    quantity_kg: quantityKg,
  });
}

export function getBooking(bookingId) {
  return getJson(`/api/bookings/${bookingId}`);
}

// ---- Queue & ETA ---------------------------------------------------------

export function checkIn({ bookingId, centreId }) {
  return postJson("/api/queue/check-in", { booking_id: bookingId, centre_id: centreId });
}

export function getLiveQueue(centreId) {
  return getJson(`/api/queue/centres/${centreId}`);
}

export function getQueueEta(queueEntryId) {
  return getJson(`/api/queue/${queueEntryId}/eta`);
}

// ---- Phase 3 adaptive scheduling ------------------------------------
// Live as of backend commit f54202e. See core/schedulingAdapter.js for the
// response contract and how the frontend consumes it.

export function getBookingSchedule(bookingId) {
  return getJson(`/api/scheduling/bookings/${bookingId}`);
}

export function getCentreSchedule(centreId) {
  return getJson(`/api/scheduling/centres/${centreId}`);
}

// ---- Staff: queue actions ------------------------------------------------
// Centre staff console operations. Farmer screens never call these.

export function callNextFarmer(centreId) {
  return postJson(`/api/queue/centres/${centreId}/call-next`, {});
}

export function startServing(queueEntryId) {
  return postJson(`/api/queue/${queueEntryId}/start-serving`, {});
}

export function completeService(queueEntryId) {
  return postJson(`/api/queue/${queueEntryId}/complete`, {});
}

export function markNoShow(queueEntryId) {
  return postJson(`/api/queue/${queueEntryId}/no-show`, {});
}

// ---- Staff: throughput ----------------------------------------------------

export function getLatestThroughput(centreId) {
  return getJson(`/api/admin/throughput/${centreId}`);
}

export function recalculateThroughput(centreId) {
  return postJson(`/api/admin/throughput/${centreId}/recalculate`, {});
}
