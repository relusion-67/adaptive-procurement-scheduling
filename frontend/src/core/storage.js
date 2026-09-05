// The backend has no authentication (by design, see project brief) and no
// "list bookings for a farmer" endpoint yet. To make the app usable across
// visits we keep two small pieces of state in localStorage on the farmer's
// own phone:
//   1. which farmer this device belongs to (id/name/phone/village)
//   2. which booking IDs this device has created or is tracking
//
// Every screen still gets its actual data live from the API - this is only
// an index of *which* booking IDs to ask the API about. See the frontend
// report / README for the backend endpoint this should be replaced by.

const FARMER_KEY = "aps.farmer";
const BOOKING_IDS_KEY = "aps.trackedBookingIds";

export function getStoredFarmer() {
  try {
    const raw = window.localStorage.getItem(FARMER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setStoredFarmer(farmer) {
  window.localStorage.setItem(FARMER_KEY, JSON.stringify(farmer));
}

export function clearStoredFarmer() {
  window.localStorage.removeItem(FARMER_KEY);
}

export function getTrackedBookingIds() {
  try {
    const raw = window.localStorage.getItem(BOOKING_IDS_KEY);
    const ids = raw ? JSON.parse(raw) : [];
    return Array.isArray(ids) ? ids : [];
  } catch {
    return [];
  }
}

export function addTrackedBookingId(bookingId) {
  const ids = getTrackedBookingIds();
  if (!ids.includes(bookingId)) {
    ids.unshift(bookingId);
    window.localStorage.setItem(BOOKING_IDS_KEY, JSON.stringify(ids));
  }
}
