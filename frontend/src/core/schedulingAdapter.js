// ---------------------------------------------------------------------
// ADAPTIVE SCHEDULING ADAPTER
// ---------------------------------------------------------------------
// This is the one place that decides ON_TRACK / AT_RISK / DELAYED and any
// recommended alternative slot or centre. Every screen calls
// getSchedulingStatus() and renders whatever comes back - none of them
// know or care whether the answer came from the real Phase 3 API or from
// the local fallback model below.
//
// STATUS: the real Phase 3 endpoints
// (GET /api/scheduling/bookings/{id}, GET /api/scheduling/centres/{id})
// are now live (backend/app/services/scheduling.py,
// backend/app/schemas/scheduling.py). This adapter's primary path talks to
// that API. The local derivation in deriveLocalSchedule() below is now a
// compatibility fallback only: it activates when the real endpoint is
// unreachable, 404s, or (defensively) returns something that doesn't match
// the documented SchedulingAssessmentResponse shape - not part of normal
// operation.
//
// REAL RESPONSE SHAPE (SchedulingAssessmentResponse):
//   scheduling_status: "ON_TRACK" | "AT_RISK" | "DELAYED"
//   recommendation: "KEEP_SLOT" | "WARN_FARMER" | "PROPOSE_NEW_SLOT" | "RECOMMEND_ALTERNATE_CENTRE"
//   farmers_ahead: int
//   average_service_minutes / estimated_wait_minutes: Decimal, serialized as a JSON STRING
//   estimated_completion_time / slot_end_time / calculated_at: ISO 8601 datetime strings (UTC offset)
//   recommended_slot_id / recommended_centre_id: int | null
//   explanation: a verbose, internal debug string built for engineers
//     (cites raw formulas and thresholds) - this is NEVER shown to a
//     farmer. The farmer-facing "reason" copy in this file is written by
//     the frontend from scheduling_status + farmers_ahead instead.
// ---------------------------------------------------------------------

import { ApiError } from "../api/client";
import {
  getBookingSchedule,
  listCentreSlots,
  listCentres,
} from "../api/endpoints";
import { combineDateAndTime, parseIsoTimestamp, toSafeNumber } from "./format";

const ACTIVE_STATUSES = new Set(["BOOKED", "CHECKED_IN", "IN_QUEUE", "PROCESSING"]);
const VALID_STATES = new Set(["ON_TRACK", "AT_RISK", "DELAYED"]);
const VALID_RECOMMENDATIONS = new Set([
  "KEEP_SLOT",
  "WARN_FARMER",
  "PROPOSE_NEW_SLOT",
  "RECOMMEND_ALTERNATE_CENTRE",
]);

// Minutes of projected delay past the slot's end time before we escalate
// the farmer-facing state. Mirrors the backend's own thresholds
// (AT_RISK_THRESHOLD_MINUTES / DELAYED_THRESHOLD_MINUTES in
// backend/app/services/scheduling.py) - only used by the local fallback,
// since the real API already classifies this server-side.
const AT_RISK_THRESHOLD_MINUTES = 10;
const DELAYED_THRESHOLD_MINUTES = 45;

/**
 * @param {object} ctx
 * @param {object} ctx.booking - BookingResponse
 * @param {object} ctx.slot - ProcurementSlotResponse for booking.slot_id
 * @param {object} ctx.centre - ProcurementCentreResponse for booking.centre_id
 * @param {object|null} ctx.queueEntry - QueueEntryResponse, if checked in
 * @param {object|null} ctx.eta - QueueETAResponse, if available
 * @returns {Promise<object|null>} scheduling status, or null if the
 *   booking is finished and there is nothing to adaptively schedule.
 */
export async function getSchedulingStatus(ctx) {
  const { booking } = ctx;

  if (!ACTIVE_STATUSES.has(booking.status)) {
    return null;
  }

  try {
    const apiResponse = await getBookingSchedule(booking.id);
    const mapped = await mapApiResponse(apiResponse, ctx);
    if (mapped) return mapped;
    // Reached a live endpoint but the payload didn't match the documented
    // SchedulingAssessmentResponse shape (e.g. an unrecognised
    // scheduling_status value) - fall through to the local model as a
    // defensive compatibility path.
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    // Network error, 404, or 5xx: the real endpoint is unavailable for this
    // booking right now - fall through to the local model.
  }

  return deriveLocalSchedule(ctx);
}

async function mapApiResponse(response, ctx) {
  if (!response || typeof response !== "object") return null;
  if (!VALID_STATES.has(response.scheduling_status)) return null;

  const state = response.scheduling_status;
  const estimatedCompletion = parseIsoTimestamp(response.estimated_completion_time);
  const slotEnd = parseIsoTimestamp(response.slot_end_time);
  const delayMinutes =
    estimatedCompletion && slotEnd
      ? Math.max(0, Math.round((estimatedCompletion - slotEnd) / 60000))
      : null;

  return {
    state,
    source: "api",
    scheduledSlot: ctx.slot,
    estimatedCompletion,
    delayMinutes,
    // Deliberately not response.explanation - see file header. Built from
    // the same farmer-facing copy the local fallback uses, so the UI reads
    // identically regardless of which path answered.
    reason: buildFarmerReason(state, response.farmers_ahead),
    recommendation: await resolveApiRecommendation(response),
  };
}

async function resolveApiRecommendation(response) {
  const type = response.recommendation;
  if (!VALID_RECOMMENDATIONS.has(type)) return null;
  if (type === "KEEP_SLOT" || type === "WARN_FARMER") {
    return { type };
  }

  // PROPOSE_NEW_SLOT / RECOMMEND_ALTERNATE_CENTRE: the API only gives back
  // ids (both nullable), which are resolved here into the full slot/centre
  // objects the UI renders, via the same existing endpoints the rest of
  // the app already uses.
  const { recommended_slot_id: slotId, recommended_centre_id: centreId } = response;
  if (slotId == null || centreId == null) {
    // Backend logic never emits PROPOSE_NEW_SLOT/RECOMMEND_ALTERNATE_CENTRE
    // without both ids, but guard defensively rather than crash the UI.
    return { type: "WARN_FARMER" };
  }

  try {
    const [centres, slots] = await Promise.all([listCentres(), listCentreSlots(centreId)]);
    const centre = centres.find((c) => c.id === centreId) ?? null;
    const slot = slots.find((s) => s.id === slotId) ?? null;
    if (!centre || !slot) return { type: "WARN_FARMER" };
    return { type, slot, centre };
  } catch {
    return { type: "WARN_FARMER" };
  }
}

function buildFarmerReason(state, farmersAhead) {
  if (state === "ON_TRACK") return null;
  return toSafeNumber(farmersAhead) > 0
    ? "Your centre is currently experiencing higher queue load than expected."
    : "Processing at your centre is currently slower than expected.";
}

// ---------------------------------------------------------------------
// LOCAL FALLBACK - only reached when the real API above is unavailable
// or unusable for this booking. See file header.
// ---------------------------------------------------------------------

async function deriveLocalSchedule({ slot, centre, queueEntry, eta }) {
  const scheduledEnd = combineDateAndTime(slot.slot_date, slot.end_time);

  // Not checked in yet: nothing live to observe, so there is nothing to be
  // at risk of yet. Still surface the feature so the farmer understands the
  // system is watching, matching the "Centre continuously observed" step
  // in the product's differentiation story.
  if (!queueEntry || !eta) {
    return {
      state: "ON_TRACK",
      source: "derived",
      scheduledSlot: slot,
      estimatedCompletion: scheduledEnd,
      delayMinutes: 0,
      reason: null,
      recommendation: { type: "KEEP_SLOT" },
    };
  }

  const now = new Date();
  const remainingMinutes =
    toSafeNumber(eta.estimated_wait_minutes) + toSafeNumber(eta.average_service_minutes);
  const estimatedCompletion = new Date(now.getTime() + remainingMinutes * 60000);
  const delayMinutes = Math.max(
    0,
    Math.round((estimatedCompletion - scheduledEnd) / 60000),
  );

  let state = "ON_TRACK";
  if (delayMinutes > DELAYED_THRESHOLD_MINUTES) state = "DELAYED";
  else if (delayMinutes > AT_RISK_THRESHOLD_MINUTES) state = "AT_RISK";

  if (state === "ON_TRACK") {
    return {
      state,
      source: "derived",
      scheduledSlot: slot,
      estimatedCompletion,
      delayMinutes,
      reason: null,
      recommendation: { type: "KEEP_SLOT" },
    };
  }

  const reason = buildFarmerReason(state, eta.farmers_ahead);

  const recommendation =
    state === "AT_RISK"
      ? await findAlternateSlotAtCentre({ centre, slot, after: estimatedCompletion })
      : await findAlternateCentre({ currentCentreId: centre.id, slot });

  return {
    state,
    source: "derived",
    scheduledSlot: slot,
    estimatedCompletion,
    delayMinutes,
    reason,
    recommendation,
  };
}

async function findAlternateSlotAtCentre({ centre, slot, after }) {
  try {
    const slots = await listCentreSlots(centre.id);
    const candidate = slots
      .filter((candidate) => candidate.id !== slot.id)
      .filter((candidate) => combineDateAndTime(candidate.slot_date, candidate.start_time) >= after)
      .sort(
        (a, b) =>
          combineDateAndTime(a.slot_date, a.start_time) -
          combineDateAndTime(b.slot_date, b.start_time),
      )[0];

    if (!candidate) return { type: "WARN_FARMER" };
    return { type: "PROPOSE_NEW_SLOT", slot: candidate, centre };
  } catch {
    return { type: "WARN_FARMER" };
  }
}

async function findAlternateCentre({ currentCentreId, slot }) {
  try {
    const centres = await listCentres();
    const otherCentres = centres.filter((c) => c.id !== currentCentreId && c.active);

    for (const candidateCentre of otherCentres) {
      const slots = await listCentreSlots(candidateCentre.id);
      const candidateSlot = slots
        .filter((s) => s.slot_date === slot.slot_date)
        .sort(
          (a, b) =>
            combineDateAndTime(a.slot_date, a.start_time) -
            combineDateAndTime(b.slot_date, b.start_time),
        )[0];
      if (candidateSlot) {
        return { type: "RECOMMEND_ALTERNATE_CENTRE", slot: candidateSlot, centre: candidateCentre };
      }
    }
    return { type: "WARN_FARMER" };
  } catch {
    return { type: "WARN_FARMER" };
  }
}
