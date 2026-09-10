import { useEffect, useState } from "react";
import { listCentres } from "../api/endpoints";
import { getAuthSession, clearAuthSession } from "../core/authStore";
import { CentreSelector } from "../components/CentreSelector";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { AffectedBookingsTable } from "../components/staff/AffectedBookingsTable";
import { CentreHealthPanel } from "../components/staff/CentreHealthPanel";
import { CurrentlyServingPanel } from "../components/staff/CurrentlyServingPanel";
import { LiveQueuePanel } from "../components/staff/LiveQueuePanel";
import { SchedulingStatusSummary } from "../components/staff/SchedulingStatusSummary";
import { ScheduledBookingsTable } from "../components/staff/ScheduledBookingsTable";
import { ProcurementRecommendations } from "../components/staff/ProcurementRecommendations";
import { IconLogOut } from "../components/icons";
import { navigate } from "../core/router";
import { useStaffDashboard } from "../hooks/useStaffDashboard";
import { StaffLogin } from "./StaffLogin";

/**
 * Desktop-oriented centre staff dashboard. Route: #/staff?centreId=<id>
 * (mirrors the ?centreId= convention already used by #/book).
 *
 * Gated behind a CENTRE_STAFF/ADMIN login: every endpoint this dashboard
 * calls (live queue, call-next/start-serving/complete/no-show, scheduling
 * assessments, throughput) requires that role server-side (see
 * backend/app/api/deps.py). A CENTRE_STAFF account is locked to its own
 * centre (ensure_centre_scope), so this screen doesn't offer a centre
 * switcher for staff - only ADMIN, who can view any centre, gets the full
 * CentreSelector.
 */
export function StaffDashboard({ params }) {
  const [session, setSession] = useState(() => getAuthSession("staff"));

  const isStaffOrAdmin = session?.role === "CENTRE_STAFF" || session?.role === "ADMIN";

  if (!isStaffOrAdmin) {
    return <StaffLogin onLoggedIn={() => setSession(getAuthSession("staff"))} />;
  }

  return (
    <StaffDashboardAuthenticated
      session={session}
      params={params}
      onLogout={() => {
        clearAuthSession("staff");
        setSession(null);
        navigate("/staff");
      }}
    />
  );
}

function StaffDashboardAuthenticated({ session, params, onLogout }) {
  const isAdmin = session.role === "ADMIN";
  // CENTRE_STAFF is locked to their own centre regardless of the URL - an
  // admin may browse any centre via the selector/URL as before.
  const centreId = isAdmin
    ? params.centreId
      ? Number(params.centreId)
      : null
    : session.centreId;

  const [centresState, setCentresState] = useState({ status: "loading", data: [] });

  useEffect(() => {
    listCentres()
      .then((data) => setCentresState({ status: "ready", data }))
      .catch(() => setCentresState({ status: "error", data: [] }));
  }, []);

  const { status, data, reload } = useStaffDashboard(centreId);

  function handleSelectCentre(id) {
    navigate(`/staff?centreId=${id}`);
  }

  return (
    <div className="screen screen--staff">
      <div className="staff-dashboard__toolbar">
        <span>
          Signed in as <strong>{session.email}</strong> ({session.role})
        </span>
        <button type="button" className="btn btn--secondary" onClick={onLogout}>
          <IconLogOut aria-hidden="true" />
          Log out
        </button>
      </div>

      {isAdmin && (
        <div>
          <h2 className="screen__section-title">Procurement centre</h2>
          {centresState.status === "loading" && <LoadingState label="Loading centres\u2026" />}
          {centresState.status === "error" && (
            <ErrorState message="We couldn't load the centre list. Please try again." />
          )}
          {centresState.status === "ready" && (
            <CentreSelector
              centres={centresState.data}
              selectedCentreId={centreId}
              onSelect={handleSelectCentre}
            />
          )}
        </div>
      )}

      {!centreId ? (
        <EmptyState
          title="Select a centre"
          message="Choose a procurement centre above to see its live dashboard."
        />
      ) : status === "loading" ? (
        <LoadingState label="Loading centre dashboard\u2026" />
      ) : status === "error" ? (
        <ErrorState
          message="We couldn't load this centre's dashboard. Please try again."
          onRetry={reload}
        />
      ) : (
        data && <StaffDashboardContent data={data} onRefresh={reload} />
      )}
    </div>
  );
}

function StaffDashboardContent({ data, onRefresh }) {
  return (
    <div className="staff-dashboard">
      <div className="staff-dashboard__col">
        <CentreHealthPanel
          centre={data.centre}
          throughput={data.throughput}
          liveQueueCount={data.liveQueueCount}
          pendingBookingsCount={data.assessments.length}
          onThroughputRecalculated={onRefresh}
        />
        <ProcurementRecommendations recommendations={data.insights.recommendations} />
        <CurrentlyServingPanel
          centreId={data.centre?.id}
          currentlyServing={data.currentlyServing}
          currentlyCalled={data.currentlyCalled}
          waitingCount={data.waitingCount}
          onActionDone={onRefresh}
        />
        <LiveQueuePanel liveQueue={data.liveQueue} />
      </div>

      <div className="staff-dashboard__col">
        <SchedulingStatusSummary
          statusCounts={data.statusCounts}
          totalTracked={data.assessments.length}
        />
        <ScheduledBookingsTable bookings={data.assessments} />
        <AffectedBookingsTable affectedBookings={data.affectedBookings} centres={data.centres} />
      </div>
    </div>
  );
}
