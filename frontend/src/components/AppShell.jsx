import { navigate } from "../core/router";
import {
  IconArrowLeft,
  IconCalendar,
  IconHistory,
  IconHome,
  IconLayoutGrid,
  IconWheat,
} from "./icons";

// Farmer-facing navigation. Shared between the mobile/tablet bottom nav and
// the desktop sidebar so the two never drift apart.
const NAV_ITEMS = [
  { path: "/", label: "Home", icon: IconHome, match: (segments) => segments.length === 0 },
  { path: "/book", label: "Book", icon: IconCalendar, match: (segments) => segments[0] === "book" },
  {
    path: "/history",
    label: "History",
    icon: IconHistory,
    match: (segments) => segments[0] === "history",
  },
];

export function AppShell({ segments, title, onBack, children }) {
  return (
    <div className="app-shell">
      <div className="app-shell__body">
        {/* Desktop-only sidebar. Hidden below the desktop breakpoint via CSS;
            the bottom nav (below) covers mobile/tablet instead. Structured
            as distinct nav "workspaces" so a Staff/Admin section can be
            added later without reshaping this component. */}
        <aside className="app-shell__sidebar" aria-label="Application">
          <div className="app-shell__sidebar-brand">
            <IconWheat aria-hidden="true" />
            <span>Adaptive Procurement</span>
          </div>

          <nav className="app-shell__sidebar-nav" aria-label="Primary">
            <p className="app-shell__sidebar-heading">Farmer</p>
            {NAV_ITEMS.map((item) => {
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

          {/* Staff/Admin workspace, separate from the farmer nav above.
              This is the desktop entry point; on tablet the equivalent
              link lives in the bottom nav instead (see
              .app-shell__nav-item--staff below) since the sidebar itself
              is desktop-only. */}
          <div className="app-shell__sidebar-future">
            <p className="app-shell__sidebar-heading">Staff &amp; admin</p>
            <button
              type="button"
              className={`app-shell__sidebar-link ${
                segments[0] === "staff" ? "app-shell__sidebar-link--active" : ""
              }`}
              onClick={() => navigate("/staff")}
              aria-current={segments[0] === "staff" ? "page" : undefined}
            >
              <IconLayoutGrid aria-hidden="true" />
              <span>Centre dashboard</span>
            </button>
          </div>
        </aside>

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
            <span className="app-shell__spacer" aria-hidden="true" />
          </header>

          <main className="app-shell__content">
            <div className="app-shell__content-inner">{children}</div>
          </main>
        </div>
      </div>

      {/* Mobile/tablet bottom nav. Hidden on desktop, where the sidebar
          above takes over. */}
      <nav className="app-shell__nav" aria-label="Primary">
        {NAV_ITEMS.map((item) => {
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

        {/* Staff/Admin entry point for tablet: shown only at tablet width
            (hidden on phone via CSS - the staff console isn't meant to fit
            there; hidden again at >=1024px, where this whole nav bar is
            replaced by the sidebar's own "Centre dashboard" link). */}
        <button
          type="button"
          className={`app-shell__nav-item app-shell__nav-item--staff ${
            segments[0] === "staff" ? "app-shell__nav-item--active" : ""
          }`}
          onClick={() => navigate("/staff")}
          aria-current={segments[0] === "staff" ? "page" : undefined}
        >
          <IconLayoutGrid aria-hidden="true" />
          <span>Staff</span>
        </button>
      </nav>
    </div>
  );
}
