import { API_BASE_URL } from "../config";

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

export async function getJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }

  return response.json();
}

export async function postJson(path, body) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }

  if (response.status === 204) return null;
  return response.json();
}
