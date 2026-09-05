import { formatDate, formatTimeRange } from "../core/format";

export function SlotSelector({ slots, selectedSlotId, onSelect }) {
  const byDate = groupByDate(slots);

  return (
    <div className="slot-selector">
      {Object.entries(byDate).map(([date, dateSlots]) => (
        <div key={date} className="slot-selector__group">
          <h3 className="slot-selector__date">{formatDate(date)}</h3>
          <div className="option-list" role="radiogroup" aria-label={`Slots on ${date}`}>
            {dateSlots.map((slot) => {
              const selected = slot.id === selectedSlotId;
              const low = slot.capacity <= 5;
              return (
                <button
                  key={slot.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  className={`option-card option-card--slot ${selected ? "option-card--selected" : ""}`}
                  onClick={() => onSelect(slot.id)}
                >
                  <span className="option-card__title">
                    {formatTimeRange(slot.start_time, slot.end_time)}
                  </span>
                  <span className={`option-card__capacity ${low ? "option-card__capacity--low" : ""}`}>
                    {slot.capacity} {slot.capacity === 1 ? "slot" : "slots"} available
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function groupByDate(slots) {
  return slots.reduce((groups, slot) => {
    (groups[slot.slot_date] ??= []).push(slot);
    return groups;
  }, {});
}
