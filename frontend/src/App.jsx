import { useEffect, useState } from "react";
import { AppShell } from "./components/AppShell";
import { LoadingState } from "./components/StateViews";
import { useHashRoute, navigate } from "./core/router";
import { clearAuthSession, getAuthSession } from "./core/authStore";
import { clearStoredFarmer, getStoredFarmer } from "./core/storage";
import { PortalSelection } from "./screens/PortalSelection";
import { Onboarding } from "./screens/Onboarding";
import { FarmerHome } from "./screens/FarmerHome";
import { BookSlot } from "./screens/BookSlot";
import { BookingConfirmation } from "./screens/BookingConfirmation";
import { TrackProcurement } from "./screens/TrackProcurement";
import { BookingHistory } from "./screens/BookingHistory";
import { StaffDashboard } from "./screens/StaffDashboard";

const TITLES = {
  home: "Adaptive Procurement Scheduling",
  portal: "Choose your portal",
  onboarding: "Farmer registration",
  book: "Book a slot",
  confirmation: "Booking confirmed",
  track: "Track procurement",
  history: "Booking history",
  staff: "Operations portal",
};

// A stored farmer profile is only useful paired with a live FARMER auth
// session. Staff/admin authentication is intentionally handled separately by
// StaffDashboard and is never represented by farmer state.
function currentFarmerSession() {
  const farmer = getStoredFarmer();
  const auth = getAuthSession("farmer");
  if (farmer && auth?.role === "FARMER" && auth.token) {
    return farmer;
  }
  if (farmer) clearStoredFarmer();
  return null;
}

function App() {
  const [farmer, setFarmer] = useState(() => currentFarmerSession());
  const route = useHashRoute();
  const { segments, params } = route;
  const [primary, secondary, tertiary] = segments;
  const isFarmerEntry = primary === "farmer";
  const farmerSegments = isFarmerEntry ? [] : segments;
  const auth = getAuthSession("farmer");
  const isStaffAuth = auth?.role === "CENTRE_STAFF" || auth?.role === "ADMIN";

  useEffect(() => {
    document.title = `${resolveTitle(segments)} – Adaptive Procurement`;
  }, [segments]);

  function finishFarmerOnboarding(profile) {
    setFarmer(profile);
    navigate("/");
  }

  // Staff/admin routes are a separate route space. StaffDashboard owns the
  // staff login state and server-authorized centre access; farmer state is not
  // involved in this branch.
  if (primary === "staff") {
    return (
      <AppShell workspace="staff" segments={segments} title={TITLES.staff}>
        <StaffDashboard params={params} />
      </AppShell>
    );
  }

  if (primary === "onboarding") {
    if (isStaffAuth && !isFarmerEntry) {
      navigate("/staff");
      return <LoadingState label="Opening operations portal…" />;
    }
    if (auth?.role === "FARMER" && farmer) {
      navigate("/");
      return <LoadingState label="Opening farmer portal…" />;
    }
    return (
      <AppShell
        workspace="farmer"
        segments={segments}
        title={TITLES.onboarding}
        showNavigation={false}
      >
        <Onboarding onDone={finishFarmerOnboarding} />
      </AppShell>
    );
  }

  if (segments.length === 0 && !auth && !isFarmerEntry) {
    return (
      <AppShell workspace="portal" segments={segments} title={TITLES.portal}>
        <PortalSelection />
      </AppShell>
    );
  }

  if (isStaffAuth && !isFarmerEntry) {
    navigate("/staff");
    return <LoadingState label="Opening operations portal…" />;
  }

  if (!farmer) {
    return (
      <AppShell
        workspace="farmer"
        segments={farmerSegments}
        title={TITLES.onboarding}
        showNavigation={false}
      >
        <Onboarding onDone={finishFarmerOnboarding} />
      </AppShell>
    );
  }

  let screen;
  let title;
  let showBack = false;

  if (isFarmerEntry || segments.length === 0) {
    screen = <FarmerHome farmer={farmer} />;
    title = TITLES.home;
  } else if (primary === "book") {
    screen = <BookSlot farmer={farmer} params={params} />;
    title = TITLES.book;
    showBack = true;
  } else if (primary === "booking" && tertiary === "confirmation") {
    screen = <BookingConfirmation bookingId={Number(secondary)} />;
    title = TITLES.confirmation;
  } else if (primary === "track" && secondary) {
    screen = <TrackProcurement bookingId={Number(secondary)} />;
    title = TITLES.track;
    showBack = true;
  } else if (primary === "history") {
    screen = <BookingHistory />;
    title = TITLES.history;
  } else {
    return <LoadingState label="Redirecting…" />;
  }

  return (
    <AppShell
      workspace="farmer"
      segments={farmerSegments}
      title={title}
      onBack={showBack ? () => window.history.back() : undefined}
      onLogout={() => {
        clearAuthSession("farmer");
        clearStoredFarmer();
        setFarmer(null);
        navigate("/");
      }}
    >
      {screen}
    </AppShell>
  );
}

function resolveTitle(segments) {
  if (segments.length === 0) return TITLES.home;
  if (segments[0] === "onboarding") return TITLES.onboarding;
  if (segments[0] === "book") return TITLES.book;
  if (segments[0] === "booking") return TITLES.confirmation;
  if (segments[0] === "track") return TITLES.track;
  if (segments[0] === "history") return TITLES.history;
  if (segments[0] === "staff") return TITLES.staff;
  return TITLES.home;
}

export default App;
