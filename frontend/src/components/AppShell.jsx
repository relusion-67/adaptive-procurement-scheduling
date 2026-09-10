import { navigate } from "../core/router";
import {
  IconArrowLeft,
  IconCalendar,
  IconHistory,
  IconHome,
  IconLayoutGrid,
  IconLogOut,
  IconWheat,
} from "./icons";

const FARMER_NAV_ITEMS = [
  { path: "/", label: "Home", icon: IconHome, match: (segments) => segments.length === 0 },
  { path: "/book", label: "Book", icon: IconCalendar, match: (segments) => segments[0] === "book" },
  {
    path: "/history",
    label: "History",
    icon: IconHistory,
    match: (segments) => segments[0] === "history",
  },
];

const STAFF_NAV_ITEMS = [
  {
    path: "/staff",
    label: "Centre dashboard",
    icon: IconLayoutGrid,
    match: (segments) => segments[0] === "staff",
  },
];

export function AppShell({
  workspace = "farmer",
  segments = [],
  title,
  onBack,
  onLogout,
  showNavigation = true,
  children,
}) {
  const navItems = workspace === "staff" ? STAFF_NAV_ITEMS : FARMER_NAV_ITEMS;
  const hasNavigation = workspace !== "portal" && showNavigation;

  return (
    <div className="app-shell">
      <div className="app-shell__body">
        {hasNavigation && (
          <aside className="app-shell__sidebar" aria-label="Application">
            <div className="app-shell__sidebar-brand">
              <IconWheat aria-hidden="true" />
              <span>Adaptive Procurement</span>
            </div>

            <nav className="app-shell__sidebar-nav" aria-label="Primary">
              <p className="app-shell__sidebar-heading">
                {workspace === "staff" ? "Operations" : "Farmer"}
              </p>
              {navItems.map((item) => {
                const active = item.match(segments);
                const Icon = item.icon;
                return (
                  <button
                    key={item.path}
                    type="button"
                    className={`app-shell__sidebar-link ${active ? "app-shell__sidebar-link--active" : ""}`}
                    onClick={() => navigate(item.path)}
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon aria-hidden="true" />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </nav>
          </aside>
        )}

        <div className="app-shell__main">
          <header className="app-shell__topbar">
            {onBack ? (
              <button type="button" className="icon-button" onClick={onBack} aria-label="Go back">
                <IconArrowLeft aria-hidden="true" />
              </button>
            ) : (
              <span className="app-shell__brand" aria-hidden="true" />
            )}
            <span className="app-shell__title">{title}</span>
            {onLogout ? (
              <button
                type="button"
                className="icon-button"
                onClick={onLogout}
                aria-label="Log out"
              >
                <IconLogOut aria-hidden="true" />
              </button>
            ) : (
              <span className="app-shell__spacer" aria-hidden="true" />
            )}
          </header>

          <main className="app-shell__content">
            <div className="app-shell__content-inner">{children}</div>
          </main>
        </div>
      </div>

      {hasNavigation && (
        <nav className="app-shell__nav" aria-label="Primary">
          {navItems.map((item) => {
            const active = item.match(segments);
            const Icon = item.icon;
            return (
              <button
                key={item.path}
                type="button"
                className={`app-shell__nav-item ${active ? "app-shell__nav-item--active" : ""}`}
                onClick={() => navigate(item.path)}
                aria-current={active ? "page" : undefined}
              >
                <Icon aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      )}
    </div>
  );
}
