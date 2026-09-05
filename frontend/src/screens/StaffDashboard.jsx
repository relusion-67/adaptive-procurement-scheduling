import { useEffect, useState } from "react";
import { listCentres } from "../api/endpoints";
import { CentreSelector } from "../components/CentreSelector";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { AffectedBookingsTable } from "../components/staff/AffectedBookingsTable";
import { CentreHealthPanel } from "../components/staff/CentreHealthPanel";
import { CurrentlyServingPanel } from "../components/staff/CurrentlyServingPanel";
import { LiveQueuePanel } from "../components/staff/LiveQueuePanel";
import { SchedulingStatusSummary } from "../components/staff/SchedulingStatusSummary";
import { navigate } from "../core/router";
import { useStaffDashboard } from "../hooks/useStaffDashboard";

/**
 * Desktop-oriented centre staff dashboard. Route: #/staff?centreId=<id>
 * (mirrors the ?centreId= convention already used by #/book).
 */
export function StaffDashboard({ params }) {
  const centreId = params.centreId ? Number(params.centreId) : null;
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
        <AffectedBookingsTable affectedBookings={data.affectedBookings} centres={data.centres} />
      </div>
    </div>
  );
}
