// Session storage for the JWT issued by POST /api/auth/login (or
// immediately after POST /api/auth/register - see Onboarding.jsx).
//
// The backend enforces JWT bearer auth + RBAC on every booking, queue,
// scheduling, and admin/throughput endpoint (see backend/app/api/deps.py).
// This module - together with the Authorization header attached in
// api/client.js - is what makes the frontend able to actually call those
// endpoints instead of getting 401s on every request.
//
// Kept deliberately tiny and framework-free (plain localStorage, like
// core/storage.js's existing farmer/booking-id persistence) rather than a
// new state-management dependency.

const AUTH_KEYS = {
  farmer: "aps.auth.farmer",
  staff: "aps.auth.staff",
};

/**
 * @typedef {Object} AuthSession
 * @property {string} token
 * @property {"FARMER"|"CENTRE_STAFF"|"ADMIN"} role
 * @property {string} email
 * @property {number|null} farmerId
 * @property {number|null} centreId
 */

/** @param {"farmer"|"staff"} portal */
export function getAuthSession(portal) {
  const key = AUTH_KEYS[portal];
  if (!key) return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** @param {"farmer"|"staff"} portal @param {AuthSession} session */
export function setAuthSession(portal, session) {
  window.localStorage.setItem(AUTH_KEYS[portal], JSON.stringify(session));
}

/** @param {"farmer"|"staff"} portal */
export function clearAuthSession(portal) {
  window.localStorage.removeItem(AUTH_KEYS[portal]);
}

export function getAuthToken() {
  const hashPath = window.location.hash.replace(/^#/, "");
  const path = hashPath || window.location.pathname;
  const portal = path.split("/").filter(Boolean)[0] === "staff" ? "staff" : "farmer";
  return getAuthSession(portal)?.token ?? null;
}
