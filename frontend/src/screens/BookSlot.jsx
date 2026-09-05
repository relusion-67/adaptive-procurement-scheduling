import { useEffect, useMemo, useState } from "react";
import { CentreSelector } from "../components/CentreSelector";
import { SlotSelector } from "../components/SlotSelector";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { createBooking, listCentreSlots, listCentres } from "../api/endpoints";
import { navigate } from "../core/router";
import { addTrackedBookingId } from "../core/storage";

const CROPS = ["Paddy", "Groundnut", "Black Gram", "Cotton", "Sugarcane", "Maize"];
const STEPS = ["Crop", "Centre", "Slot", "Confirm"];

export function BookSlot({ farmer, params }) {
  const [step, setStep] = useState(0);
  const [cropType, setCropType] = useState("");
  const [quantityKg, setQuantityKg] = useState("");
  const [centreId, setCentreId] = useState(params.centreId ? Number(params.centreId) : null);
  const [slotId, setSlotId] = useState(params.slotId ? Number(params.slotId) : null);

  const [centres, setCentres] = useState({ status: "loading", data: [] });
  const [slotsState, setSlotsState] = useState({ centreId: null, status: "idle", data: [] });
  const [slotsRetryToken, setSlotsRetryToken] = useState(0);
  const [submit, setSubmit] = useState({ status: "idle", error: null });

  useEffect(() => {
    listCentres()
      .then((data) => setCentres({ status: "ready", data }))
      .catch(() => setCentres({ status: "error", data: [] }));
  }, []);

  useEffect(() => {
    if (!centreId) return undefined;
    listCentreSlots(centreId)
      .then((data) => setSlotsState({ centreId, status: "ready", data }))
      .catch(() => setSlotsState({ centreId, status: "error", data: [] }));
    return undefined;
    // slotsRetryToken deliberately triggers a refetch without changing
    // centreId itself.
  }, [centreId, slotsRetryToken]);

  // Derived rather than reset synchronously in the effect above: while a
  // fetch for the newly-selected centre is in flight, slotsState still
  // reflects the previous centre, so treat that as "loading" for this one.
  const slots =
    !centreId
      ? { status: "idle", data: [] }
      : slotsState.centreId === centreId
        ? slotsState
        : { status: "loading", data: [] };

  const selectedCentre = useMemo(
    () => centres.data.find((c) => c.id === centreId) ?? null,
    [centres.data, centreId],
  );
  const selectedSlot = useMemo(
    () => slots.data.find((s) => s.id === slotId) ?? null,
    [slots.data, slotId],
  );

  const canProceed = [
    Boolean(cropType),
    Boolean(centreId),
    Boolean(slotId),
    Boolean(cropType && centreId && slotId && quantityKg && Number(quantityKg) > 0),
  ];

  async function handleConfirm() {
    setSubmit({ status: "loading", error: null });
    try {
      const booking = await createBooking({
        farmerId: farmer.id,
        centreId,
        slotId,
        cropType,
        quantityKg: Number(quantityKg),
      });
      addTrackedBookingId(booking.id);
      navigate(`/booking/${booking.id}/confirmation`);
    } catch (error) {
      setSubmit({
        status: "error",
        error: error.message || "We couldn't complete your booking. Please try again.",
      });
    }
  }

  return (
    <div className="screen">
      <ol className="stepper" aria-label="Booking steps">
        {STEPS.map((label, index) => (
          <li
            key={label}
            className={`stepper__step ${index === step ? "stepper__step--active" : ""} ${index < step ? "stepper__step--done" : ""}`}
          >
            {label}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <section className="screen__step">
          <h2>What are you bringing?</h2>
          <div className="option-list option-list--grid">
            {CROPS.map((crop) => (
              <button
                key={crop}
                type="button"
                className={`option-chip ${cropType === crop ? "option-chip--selected" : ""}`}
                onClick={() => setCropType(crop)}
              >
                {crop}
              </button>
            ))}
          </div>
        </section>
      )}

      {step === 1 && (
        <section className="screen__step">
          <h2>Choose a procurement centre</h2>
          {centres.status === "loading" && <LoadingState label="Loading centres\u2026" />}
          {centres.status === "error" && (
            <ErrorState onRetry={() => setCentres({ status: "loading", data: [] })} />
          )}
          {centres.status === "ready" && centres.data.length === 0 && (
            <EmptyState message="No procurement centres are available right now." />
          )}
          {centres.status === "ready" && centres.data.length > 0 && (
            <CentreSelector
              centres={centres.data}
              selectedCentreId={centreId}
              onSelect={(id) => {
                setCentreId(id);
                setSlotId(null);
              }}
            />
          )}
        </section>
      )}

      {step === 2 && (
        <section className="screen__step">
          <h2>Choose a slot</h2>
          {slots.status === "loading" && <LoadingState label="Loading available slots\u2026" />}
          {slots.status === "error" && (
            <ErrorState onRetry={() => setSlotsRetryToken((token) => token + 1)} />
          )}
          {slots.status === "ready" && slots.data.length === 0 && (
            <EmptyState message="No open slots at this centre right now. Try another centre." />
          )}
          {slots.status === "ready" && slots.data.length > 0 && (
            <SlotSelector slots={slots.data} selectedSlotId={slotId} onSelect={setSlotId} />
          )}
        </section>
      )}

      {step === 3 && (
        <section className="screen__step">
          <h2>Confirm your booking</h2>
          <dl className="review-list">
            <div>
              <dt>Crop</dt>
              <dd>{cropType}</dd>
            </div>
            <div>
              <dt>Centre</dt>
              <dd>{selectedCentre?.name}</dd>
            </div>
            <div>
              <dt>Slot</dt>
              <dd>
                {selectedSlot &&
                  `${selectedSlot.slot_date}, ${selectedSlot.start_time.slice(0, 5)}\u2013${selectedSlot.end_time.slice(0, 5)}`}
              </dd>
            </div>
          </dl>

          <label className="field">
            <span>Quantity (kg)</span>
            <input
              type="number"
              min="1"
              step="0.01"
              inputMode="decimal"
              value={quantityKg}
              onChange={(event) => setQuantityKg(event.target.value)}
              placeholder="e.g. 500"
            />
          </label>

          {submit.status === "error" && (
            <p className="form__error" role="alert">
              {submit.error}
            </p>
          )}
        </section>
      )}

      <div className="screen__step-actions">
        {step > 0 && (
          <button type="button" className="btn btn--secondary" onClick={() => setStep(step - 1)}>
            Back
          </button>
        )}
        {step < STEPS.length - 1 ? (
          <button
            type="button"
            className="btn btn--primary"
            disabled={!canProceed[step]}
            onClick={() => setStep(step + 1)}
          >
            Next
          </button>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            disabled={!canProceed[3] || submit.status === "loading"}
            onClick={handleConfirm}
          >
            {submit.status === "loading" ? "Booking\u2026" : "Confirm booking"}
          </button>
        )}
      </div>
    </div>
  );
}
