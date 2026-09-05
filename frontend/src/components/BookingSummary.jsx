import { formatDate, formatQuantity, formatTimeRange } from "../core/format";
import { BOOKING_STATUS_LABELS } from "../core/statusLabels";
import { StatusBadge } from "./StatusBadge";
import { BOOKING_STATUS_TONE } from "./statusTone";
import { IconCalendar, IconClock, IconMapPin, IconWheat } from "./icons";

export function BookingSummary({ booking, slot, centre, compact = false }) {
  return (
    <div className={`booking-summary ${compact ? "booking-summary--compact" : ""}`}>
      <div className="booking-summary__header">
        <div className="booking-summary__crop">
          <IconWheat aria-hidden="true" />
          <span>{booking.crop_type}</span>
        </div>
        <StatusBadge
          label={BOOKING_STATUS_LABELS[booking.status] ?? booking.status}
          tone={BOOKING_STATUS_TONE[booking.status] ?? "neutral"}
        />
      </div>

      <dl className="booking-summary__details">
        <div>
          <dt>
            <IconMapPin aria-hidden="true" />
            Centre
          </dt>
          <dd>{centre?.name ?? "\u2014"}</dd>
        </div>
        {slot && (
          <>
            <div>
              <dt>
                <IconCalendar aria-hidden="true" />
                Date
              </dt>
              <dd>{formatDate(slot.slot_date)}</dd>
            </div>
            <div>
              <dt>
                <IconClock aria-hidden="true" />
                Time
              </dt>
              <dd>{formatTimeRange(slot.start_time, slot.end_time)}</dd>
            </div>
          </>
        )}
        {!compact && (
          <div>
            <dt>Quantity</dt>
            <dd>{formatQuantity(booking.quantity_kg)}</dd>
          </div>
        )}
      </dl>
    </div>
  );
}
