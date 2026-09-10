import { useState } from "react";
import { createFarmer, getCurrentUser, getFarmer, login, registerUser } from "../api/endpoints";
import { clearAuthSession, setAuthSession } from "../core/authStore";
import { setStoredFarmer } from "../core/storage";
import { IconWheat } from "../components/icons";

// The backend requires a JWT bearer token for booking/queue/scheduling
// endpoints (see backend/app/api/deps.py), so "onboarding" now has to do
// two things, not one: create the Farmer profile (name/phone/village, the
// pre-existing domain record) AND create+log into the FARMER user account
// that authorizes booking on that profile's behalf. Both happen here in
// one form so a new farmer still only fills in one screen.
//
// Returning farmers (same device or a new one) use the "Log in instead"
// toggle, which only needs email/password - the farmer profile itself is
// re-fetched via GET /api/farmers/{id} using the farmer_id embedded in
// their account (see /api/auth/me).

export function Onboarding({ onDone }) {
  const [mode, setMode] = useState("signup"); // "signup" | "login"
  const [form, setForm] = useState({
    name: "",
    phone: "",
    village: "",
    email: "",
    password: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const update = (field) => (event) =>
    setForm((prev) => ({ ...prev, [field]: event.target.value }));

  function completeSession(user, token, farmer) {
    setAuthSession("farmer", {
      token,
      role: user.role,
      email: user.email,
      farmerId: user.farmer_id,
      centreId: user.centre_id,
    });
    setStoredFarmer(farmer);
    onDone(farmer);
  }

  async function handleSignUp(event) {
  event.preventDefault();
  setSubmitting(true);
  setError(null);

  try {
    const farmer = await createFarmer({
      name: form.name,
      phone: form.phone,
      village: form.village,
    });

    await registerUser({
      email: form.email,
      password: form.password,
      role: "FARMER",
      farmerId: farmer.id,
    });

    const { access_token: token } = await login({
      email: form.email,
      password: form.password,
    });

    setAuthSession("farmer", { token, role: "FARMER", email: form.email, farmerId: null, centreId: null });
    const user = await getCurrentUser();
    if (user.role !== "FARMER" || user.farmer_id !== farmer.id) {
      throw new Error("Registered account is not a farmer account");
    }

    completeSession(user, token, farmer);
  } catch (error) {
    setError(error?.message || "Signup failed. Please try again.");
  } finally {
    setSubmitting(false);
  }
}

  async function handleLogIn(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { access_token: token } = await login({
        email: form.email,
        password: form.password,
      });
      // getCurrentUser() reads the token via authHeaders(), which reads
      // straight from localStorage - store the session before calling it.
      setAuthSession("farmer", { token, role: "FARMER", email: form.email, farmerId: null, centreId: null });
      const user = await getCurrentUser();
      if (user.role !== "FARMER" || !user.farmer_id) {
        throw new Error("Not a farmer account");
      }
      const farmer = await getFarmer(user.farmer_id);
      completeSession(user, token, farmer);
   } catch (error) {
     clearAuthSession("farmer");
     setError(error?.message || "Login failed. Please try again.");
   } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="onboarding">
      <div className="onboarding__intro">
        <IconWheat className="onboarding__icon" aria-hidden="true" />
        <h1>Adaptive Procurement Scheduling</h1>
        <p>
          Book your procurement slot, track your place in the queue, and get
          told early if your centre is running behind {"\u2014"} so you know
          before you leave home.
        </p>
      </div>

      {mode === "signup" ? (
        <form className="form" onSubmit={handleSignUp}>
          <h2>Tell us about yourself</h2>

          <label className="field">
            <span>Full name</span>
            <input
              required
              type="text"
              value={form.name}
              onChange={update("name")}
              placeholder="e.g. Arun Kumar"
              autoComplete="name"
            />
          </label>

          <label className="field">
            <span>Phone number</span>
            <input
              required
              type="tel"
              inputMode="numeric"
              pattern="[0-9]{10}"
              value={form.phone}
              onChange={update("phone")}
              placeholder="10-digit mobile number"
              autoComplete="tel"
            />
          </label>

          <label className="field">
            <span>Village</span>
            <input
              required
              type="text"
              value={form.village}
              onChange={update("village")}
              placeholder="e.g. Vallam"
              autoComplete="address-level3"
            />
          </label>

          <label className="field">
            <span>Email</span>
            <input
              required
              type="email"
              value={form.email}
              onChange={update("email")}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </label>

          <label className="field">
            <span>Password</span>
            <input
              required
              type="password"
              minLength={8}
              value={form.password}
              onChange={update("password")}
              placeholder="At least 8 characters"
              autoComplete="new-password"
            />
          </label>

          {error && (
            <p className="form__error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            {submitting ? "Saving\u2026" : "Continue"}
          </button>

          <button
            type="button"
            className="btn btn--secondary btn--block"
            onClick={() => {
              setMode("login");
              setError(null);
            }}
          >
            Already registered? Log in instead
          </button>
        </form>
      ) : (
        <form className="form" onSubmit={handleLogIn}>
          <h2>Log in</h2>

          <label className="field">
            <span>Email</span>
            <input
              required
              type="email"
              value={form.email}
              onChange={update("email")}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </label>

          <label className="field">
            <span>Password</span>
            <input
              required
              type="password"
              value={form.password}
              onChange={update("password")}
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

          <button
            type="button"
            className="btn btn--secondary btn--block"
            onClick={() => {
              setMode("signup");
              setError(null);
            }}
          >
            New here? Sign up instead
          </button>
        </form>
      )}
    </div>
  );
}
