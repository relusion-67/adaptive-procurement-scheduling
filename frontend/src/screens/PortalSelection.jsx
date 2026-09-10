import { navigate } from "../core/router";
import { IconWheat } from "../components/icons";

export function PortalSelection() {
  return (
    <div className="onboarding">
      <div className="onboarding__intro">
        <IconWheat className="onboarding__icon" aria-hidden="true" />
        <h1>Tamil Nadu Procurement Services</h1>
        <p>
          Select the service area that matches your role. Farmer services support
          slot booking and procurement tracking. Staff and administrators use the
          operations portal to monitor centre activity.
        </p>
      </div>

      <div className="screen__actions">
        <button type="button" className="btn btn--primary btn--block" onClick={() => navigate("/onboarding")}>
          Farmer Portal
        </button>
        <button type="button" className="btn btn--secondary btn--block" onClick={() => navigate("/staff")}>
          Staff/Admin Operations Portal
        </button>
      </div>
    </div>
  );
}
