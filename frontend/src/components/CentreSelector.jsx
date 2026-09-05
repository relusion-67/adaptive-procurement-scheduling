import { IconMapPin } from "./icons";

export function CentreSelector({ centres, selectedCentreId, onSelect }) {
  return (
    <div className="option-list" role="radiogroup" aria-label="Procurement centre">
      {centres.map((centre) => {
        const selected = centre.id === selectedCentreId;
        return (
          <button
            key={centre.id}
            type="button"
            role="radio"
            aria-checked={selected}
            className={`option-card ${selected ? "option-card--selected" : ""}`}
            onClick={() => onSelect(centre.id)}
          >
            <IconMapPin aria-hidden="true" />
            <span>
              <span className="option-card__title">{centre.name}</span>
              <span className="option-card__subtitle">{centre.district} district</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
