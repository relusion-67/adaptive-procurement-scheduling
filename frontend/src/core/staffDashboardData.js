// ---------------------------------------------------------------------
// STAFF DASHBOARD DATA
// ---------------------------------------------------------------------
// The one place that fetches and assembles the centre staff dashboard's
// cross-endpoint data, so screens/components stay presentation-only -
// mirrors the role core/schedulingAdapter.js plays for the farmer app.
//
// Every value returned here either comes straight from a backend response
// (see the field's source endpoint in the comments below) or is explicitly
// computed client-side, in which case it is named/commented as "derived"
// here AND labelled as derived wherever it is shown in the UI. Nothing in
// this module invents a metric the backend doesn't already give us the
// inputs for.
// ---------------------------------------------------------------------

import { ApiError } from "../api/client";
import {
  getCentreSchedule,
  getLatestThroughput,
  getLiveQueue,
  listCentres,
} from "../api/endpoints";

export const SCHEDULING_STATES = ["ON_TRACK", "AT_RISK", "DELAYED"];

/**
 * Loads and assembles everything the staff dashboard needs for one centre.
 *
 * @param {number} centreId
 * @returns {Promise<{
 *   centre: object|null,
 *   centres: object[],
 *   liveQueue: object[],
 *   liveQueueCount: number,
 *   currentlyServing: object|null,
 *   currentlyCalled: object|null,
 *   waitingCount: number,
 *   assessments: object[],
 *   statusCounts: {ON_TRACK: number, AT_RISK: number, DELAYED: number},
 *   affectedBookings: object[],
 *   throughput: {status: "available"|"unavailable", snapshot: object|null},
 * }>}
 */
export async function loadStaffDashboard(centreId) {
  const [centres, liveQueue, assessments, throughput] = await Promise.all([
    listCentres(), // GET /api/centres/
    getLiveQueue(centreId), // GET /api/queue/centres/{id}
    getCentreSchedule(centreId), // GET /api/scheduling/centres/{id}
    loadThroughput(centreId), // GET /api/admin/throughput/{id}
  ]);

  const centre = centres.find((c) => c.id === centreId) ?? null;

  // "Currently serving" / "currently called" are not separate backend
  // fields - they're derived by reading queue_status off the live queue
  // list, which the backend already orders SERVING -> CALLED -> WAITING.
  const currentlyServing = liveQueue.find((entry) => entry.queue_status === "SERVING") ?? null;
  const currentlyCalled = liveQueue.find((entry) => entry.queue_status === "CALLED") ?? null;
  const waitingCount = liveQueue.filter((entry) => entry.queue_status === "WAITING").length;

  // Derived: the backend does not expose pre-aggregated ON_TRACK / AT_RISK
  // / DELAYED counts, so this tallies the per-booking scheduling_status
  // values already present in the assess_centre response.
  const statusCounts = { ON_TRACK: 0, AT_RISK: 0, DELAYED: 0 };
  for (const assessment of assessments) {
    if (assessment.scheduling_status in statusCounts) {
      statusCounts[assessment.scheduling_status] += 1;
    }
  }

  // Derived: same source list, filtered to anything not ON_TRACK.
  const affectedBookings = assessments.filter((a) => a.scheduling_status !== "ON_TRACK");

  return {
    centre,
    centres,
    liveQueue,
    liveQueueCount: liveQueue.length,
    currentlyServing,
    currentlyCalled,
    waitingCount,
    assessments,
    statusCounts,
    affectedBookings,
    throughput,
  };
}

async function loadThroughput(centreId) {
  try {
    const snapshot = await getLatestThroughput(centreId);
    return { status: "available", snapshot };
  } catch (error) {
    // A centre with no completed queue history yet is an ordinary state
    // (see backend/app/services/throughput.py), surfaced as a 404 - treat
    // it as "no data yet", not an error.
    if (error instanceof ApiError && error.status === 404) {
      return { status: "unavailable", snapshot: null };
    }
    throw error;
  }
}

/** Looks up a centre's name from an already-fetched centre list. */
export function resolveCentreName(centres, centreId) {
  if (centreId == null) return null;
  return centres.find((c) => c.id === centreId)?.name ?? null;
}
