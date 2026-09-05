// A small, purpose-built icon set. Each icon is a plain inline SVG using
// currentColor so it inherits text color/contrast automatically - no icon
// library needed for a dozen glyphs, which keeps the bundle light for
// low-bandwidth connections.
const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export function IconHome(props) {
  return (
    <svg {...base} {...props}>
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5.5 10v9a1 1 0 0 0 1 1H9a1 1 0 0 0 1-1v-4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v4a1 1 0 0 0 1 1h2.5a1 1 0 0 0 1-1v-9" />
    </svg>
  );
}

export function IconCalendar(props) {
  return (
    <svg {...base} {...props}>
      <rect x="3.5" y="5" width="17" height="16" rx="2" />
      <path d="M8 3v4M16 3v4M3.5 10h17" />
    </svg>
  );
}

export function IconMapPin(props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 21s7-6.5 7-11.5A7 7 0 0 0 5 9.5C5 14.5 12 21 12 21Z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </svg>
  );
}

export function IconClock(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

export function IconUsers(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="3" />
      <path d="M3 19c0-3 2.7-5 6-5s6 2 6 5" />
      <path d="M16 5.2a3 3 0 0 1 0 5.8" />
      <path d="M18.5 14.3c2 .5 3.5 2.2 3.5 4.7" />
    </svg>
  );
}

export function IconCheckCircle(props) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12.3l2.4 2.4 4.7-5" />
    </svg>
  );
}

export function IconAlertTriangle(props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 4.5 21 19H3L12 4.5Z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="16.7" r="0.15" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconAlertOctagon(props) {
  return (
    <svg {...base} {...props}>
      <path d="M8 3.5h8L21 8v8l-5 4.5H8L3 16V8L8 3.5Z" />
      <path d="M12 8v5" />
      <circle cx="12" cy="15.7" r="0.15" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconWheat(props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 3v18" />
      <path d="M12 6c-2 0-3.5 1.2-3.5 2.8S10 11 12 11s3.5 1.2 3.5 2.8S14 16.5 12 16.5" />
      <path d="M9 8.2 6.5 6M15 8.2 17.5 6M9 13.6l-2.5 2.2M15 13.6l2.5 2.2" />
    </svg>
  );
}

export function IconArrowLeft(props) {
  return (
    <svg {...base} {...props}>
      <path d="M19 12H5" />
      <path d="M11 6l-6 6 6 6" />
    </svg>
  );
}

export function IconChevronRight(props) {
  return (
    <svg {...base} {...props}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function IconHistory(props) {
  return (
    <svg {...base} {...props}>
      <path d="M4 12a8 8 0 1 0 2.6-5.9" />
      <path d="M4 4v4.5H8.5" />
      <path d="M12 8v4.5l3 2" />
    </svg>
  );
}

export function IconTicket(props) {
  return (
    <svg {...base} {...props}>
      <path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h13A1.5 1.5 0 0 1 20 8.5v1.4a1.6 1.6 0 0 0 0 3.2v1.4A1.5 1.5 0 0 1 18.5 16h-13A1.5 1.5 0 0 1 4 14.5v-1.4a1.6 1.6 0 0 0 0-3.2Z" />
      <path d="M14 7v9" strokeDasharray="1.5 2.2" />
    </svg>
  );
}

export function IconSignal(props) {
  return (
    <svg {...base} {...props}>
      <path d="M4 18v-3M9.5 18v-6M15 18V9M20 18V4" />
    </svg>
  );
}

export function IconRefresh(props) {
  return (
    <svg {...base} {...props}>
      <path d="M20 11A8 8 0 0 0 5.5 6.5L4 8" />
      <path d="M4 4v4h4" />
      <path d="M4 13a8 8 0 0 0 14.5 4.5L20 16" />
      <path d="M20 20v-4h-4" />
    </svg>
  );
}

// Reserved for the desktop sidebar's Staff/Admin placeholder section - not
// used by any farmer-facing screen.
export function IconLayoutGrid(props) {
  return (
    <svg {...base} {...props}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.2" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.2" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.2" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.2" />
    </svg>
  );
}
