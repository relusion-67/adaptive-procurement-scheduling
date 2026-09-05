# adaptive-procurement-scheduling
Adaptive procurement scheduling and real-time queue management platform designed to reduce farmer waiting time and uncertainty at procurement centres.

## Project foundation (Phase 1)

- Backend: FastAPI modular monolith scaffold in `backend/app/`
- Frontend: React + Vite scaffold in `frontend/`
- Configuration template: `.env.example`

## Authentication & authorization (Phase 4 - production hardening)

The API requires JWT bearer authentication for every endpoint that
touches a specific farmer's, centre's, or admin-only data. Three roles
exist: `FARMER`, `CENTRE_STAFF` (scoped to exactly one procurement
centre), and `ADMIN`.

- `POST /api/auth/register` - self-registration for `FARMER` (requires an
  existing `farmer_id` from `POST /api/farmers/`) and `CENTRE_STAFF`
  (requires an existing `centre_id`). `ADMIN` cannot be self-registered;
  provision admin accounts out-of-band.
- `POST /api/auth/login` - OAuth2 password flow (`username` = email);
  returns a bearer access token.
- `GET /api/auth/me` - current authenticated user.

Remaining endpoints stay public where the data is non-sensitive
(browsing centres/slots, creating a farmer profile, the documented
placeholder modules). Booking, queue, scheduling, and admin/throughput
endpoints enforce ownership/centre-scope/role checks server-side - see
`backend/app/api/deps.py` for the shared dependencies and
`backend/tests/test_security.py` for the behavioral test coverage.

**Known limitation:** the React frontend in `frontend/` does not yet have
a login UI or token storage; it was intentionally left untouched. Wiring
up frontend authentication is out of scope for this hardening milestone
and is tracked as follow-up work.
