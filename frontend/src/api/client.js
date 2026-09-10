import { API_BASE_URL } from "../config";
import { clearAuthSession, getAuthToken } from "../core/authStore";

/**
 * Error thrown for any non-2xx API response. Carries the HTTP status so
 * callers (e.g. the scheduling adapter) can distinguish "not implemented
 * yet" (404) from real failures without parsing message strings.
 */
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseErrorDetail(response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Response wasn't JSON (or was empty) - fall through to the default.
  }
  return `Request failed: ${response.status}`;
}

// Every request that isn't the login/register endpoints themselves goes
// through here so the bearer token (if any) is attached automatically -
// individual screens/endpoints never have to remember to add it. A 401
// means the token is missing/expired/invalid; clearing the stored session
// here (rather than in every caller) means the next protected call, or the
// next app load, correctly falls back to a login/onboarding screen instead
// of silently retrying with a dead token.
function authHeaders() {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handleResponse(response) {
  if (!response.ok) {
    if (response.status === 401) {
      const hashPath = window.location.hash.replace(/^#/, "");
      const path = hashPath || window.location.pathname;
      clearAuthSession(path.split("/").filter(Boolean)[0] === "staff" ? "staff" : "farmer");
    }
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function getJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { ...authHeaders() },
  });
  return handleResponse(response);
}

export async function postJson(path, body) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}

// POST /api/auth/login is an OAuth2PasswordRequestForm endpoint (FastAPI's
// standard password flow), which requires a form-encoded body with
// `username`/`password` fields - not JSON like every other endpoint here.
// This never needs an Authorization header (it's how you get the token in
// the first place).
export async function postForm(path, fields) {
  const body = new URLSearchParams(fields);
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return handleResponse(response);
}
