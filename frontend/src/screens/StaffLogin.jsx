import { useState } from "react";
import { getCurrentUser, login } from "../api/endpoints";
import { clearAuthSession, setAuthSession } from "../core/authStore";

// Gate in front of StaffDashboard: the live queue, call-next/complete/
// no-show actions, scheduling assessments, and throughput endpoints all
// require an authenticated CENTRE_STAFF or ADMIN (see
// backend/app/api/deps.py's require_centre_staff_or_admin /
// ensure_centre_scope). There is no self-registration for either role -
// see the seed demo accounts in backend/app/db/seed.py (DEMO_ADMIN /
// DEMO_STAFF) for local/demo credentials, or POST /api/admin/users for
// provisioning a real one.
export function StaffLogin({ onLoggedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { access_token: token } = await login({ email, password });
      setAuthSession("staff", { token, role: null, email, farmerId: null, centreId: null });
      const user = await getCurrentUser();
      if (user.role !== "CENTRE_STAFF" && user.role !== "ADMIN") {
        throw new Error("Not a staff/admin account");
      }
      setAuthSession("staff", {
        token,
        role: user.role,
        email: user.email,
        farmerId: user.farmer_id,
        centreId: user.centre_id,
      });
      onLoggedIn(user);
    } catch {
      clearAuthSession("staff");
      setError("We couldn't log you in. Check your email and password and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="onboarding">
      <div className="onboarding__intro">
        <h1>Centre staff &amp; admin</h1>
        <p>Log in with your centre staff or admin account to open the live dashboard.</p>
      </div>

      <form className="form" onSubmit={handleSubmit}>
        <label className="field">
          <span>Email</span>
          <input
            required
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            autoComplete="email"
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            required
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>

        {error && (
          <p className="form__error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
          {submitting ? "Logging in\u2026" : "Log in"}
        </button>
      </form>
    </div>
  );
}
