import { IconAlertOctagon, IconAlertTriangle, IconCheckCircle, IconClock } from "./icons";

// Every status tone pairs a color with a distinct icon, so state is never
// carried by color alone (accessibility requirement, section 21).
const TONE_CONFIG = {
  neutral: { icon: IconClock, className: "badge--neutral" },
  good: { icon: IconCheckCircle, className: "badge--good" },
  warning: { icon: IconAlertTriangle, className: "badge--warning" },
  danger: { icon: IconAlertOctagon, className: "badge--danger" },
};

export function StatusBadge({ label, tone = "neutral" }) {
  const { icon: Icon, className } = TONE_CONFIG[tone] ?? TONE_CONFIG.neutral;
  return (
    <span className={`badge ${className}`}>
      <Icon aria-hidden="true" />
      {label}
    </span>
  );
}
