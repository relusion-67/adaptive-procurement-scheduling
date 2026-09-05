import { useState } from "react";
import { createFarmer } from "../api/endpoints";
import { setStoredFarmer } from "../core/storage";
import { IconWheat } from "../components/icons";

export function Onboarding({ onDone }) {
  const [form, setForm] = useState({ name: "", phone: "", village: "" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const update = (field) => (event) =>
    setForm((prev) => ({ ...prev, [field]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const farmer = await createFarmer(form);
      setStoredFarmer(farmer);
      onDone(farmer);
    } catch {
      setError("We couldn't save your details. Please check and try again.");
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

      <form className="form" onSubmit={handleSubmit}>
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

        {error && (
          <p className="form__error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
          {submitting ? "Saving\u2026" : "Continue"}
        </button>
      </form>
    </div>
  );
}
