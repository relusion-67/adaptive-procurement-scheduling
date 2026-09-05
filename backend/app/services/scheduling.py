from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, ProcurementSlot, QueueStatus
from app.repositories import bookings as booking_repository
from app.repositories import procurement as procurement_repository
from app.repositories import queue as queue_repository
from app.repositories import throughput as throughput_repository
from app.services import eta as eta_service

# Buffer thresholds (minutes) applied against a booking's slot end time.
# Mirrors the deterministic, product-specified ADAPT rules: a booking is
# only AT_RISK once its estimated completion meaningfully overruns the
# slot, and only DELAYED once that overrun is substantial.
AT_RISK_THRESHOLD_MINUTES = Decimal("10")
DELAYED_THRESHOLD_MINUTES = Decimal("45")

# Queue entries in these states represent a farmer who is physically present
# and actively waiting/being served right now.
LIVE_QUEUE_STATUSES = (QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.SERVING)


class SchedulingStatus(str, enum.Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    DELAYED = "DELAYED"


class SchedulingRecommendation(str, enum.Enum):
    KEEP_SLOT = "KEEP_SLOT"
    WARN_FARMER = "WARN_FARMER"
    PROPOSE_NEW_SLOT = "PROPOSE_NEW_SLOT"
    RECOMMEND_ALTERNATE_CENTRE = "RECOMMEND_ALTERNATE_CENTRE"


@dataclass
class SchedulingError(Exception):
    detail: str
    status_code: int


@dataclass
class SchedulingAssessment:
    booking_id: int
    centre_id: int
    slot_id: int
    scheduling_status: SchedulingStatus
    recommendation: SchedulingRecommendation
    farmers_ahead: int
    average_service_minutes: Decimal
    estimated_wait_minutes: Decimal
    estimated_completion_time: datetime
    slot_end_time: datetime
    is_forecast: bool
    recommended_slot_id: int | None
    recommended_centre_id: int | None
    explanation: str
    calculated_at: datetime


def assess_booking(session: Session, booking_id: int) -> SchedulingAssessment:
    """Public entry point for GET /scheduling/bookings/{booking_id}."""
    booking = booking_repository.get_booking(session, booking_id)
    if booking is None:
        raise SchedulingError("Booking not found", 404)
    return _assess(session, booking)


def assess_centre(session: Session, centre_id: int) -> list[SchedulingAssessment]:
    """Public entry point for GET /scheduling/centres/{centre_id}.

    Assesses every booking at the centre that hasn't yet reached a terminal
    state, in the same slot order the ESTIMATE stage itself relies on.
    """
    centre = procurement_repository.get_centre(session, centre_id)
    if centre is None:
        raise SchedulingError("Procurement centre not found", 404)

    pending_bookings = booking_repository.list_pending_bookings_for_centre(session, centre_id)
    return [_assess(session, booking) for booking in pending_bookings]


# --------------------------------------------------------------------------
# OBSERVE + ESTIMATE + ADAPT for a single booking
# --------------------------------------------------------------------------


def _assess(session: Session, booking: Booking) -> SchedulingAssessment:
    slot = booking.slot

    # OBSERVE: does this booking already have a live queue entry, or is it
    # still upstream of check-in? This is the fork between "use the real
    # queue position" and "forecast from scheduled demand".
    queue_entry = queue_repository.get_queue_entry_for_booking(session, booking.id)
    live_entry = (
        queue_entry
        if queue_entry is not None and queue_entry.queue_status in LIVE_QUEUE_STATUSES
        else None
    )

    # ESTIMATE
    forecast_detail: _ForecastEstimate | None = None
    if live_entry is not None:
        is_forecast = False
        queue_eta = eta_service.calculate_eta(session, live_entry.id)
        farmers_ahead = queue_eta.farmers_ahead
        average_service_minutes = queue_eta.average_service_minutes
        estimated_wait_minutes = queue_eta.estimated_wait_minutes
        calculated_at = queue_eta.calculated_at
    else:
        # Not checked in: answer "is this farmer's assigned slot on track?",
        # anchored to the slot itself - not "if they checked in this
        # instant, when would they finish?". See _forecast_estimate for the
        # full carryover/ahead-demand projection.
        is_forecast = True
        calculated_at = datetime.now(timezone.utc)
        average_service_minutes = _average_service_minutes(session, booking.centre_id)
        forecast_detail = _forecast_estimate(
            session, booking, slot, calculated_at, average_service_minutes
        )
        farmers_ahead = forecast_detail.farmers_ahead
        estimated_wait_minutes = forecast_detail.estimated_wait_minutes

    estimated_completion_time = calculated_at + timedelta(
        minutes=float(estimated_wait_minutes)
    )
    slot_end_time = _slot_datetime(slot.slot_date, slot.end_time)
    overrun_minutes = Decimal(
        (estimated_completion_time - slot_end_time).total_seconds()
    ) / Decimal(60)

    # ADAPT: classify against the deterministic overrun thresholds. A
    # booking already recorded as MISSED is DELAYED regardless of what the
    # estimate says, since the farmer's slot has already been lost.
    if booking.status == BookingStatus.MISSED:
        scheduling_status = SchedulingStatus.DELAYED
    elif overrun_minutes <= AT_RISK_THRESHOLD_MINUTES:
        scheduling_status = SchedulingStatus.ON_TRACK
    elif overrun_minutes <= DELAYED_THRESHOLD_MINUTES:
        scheduling_status = SchedulingStatus.AT_RISK
    else:
        scheduling_status = SchedulingStatus.DELAYED

    recommendation, recommended_slot_id, recommended_centre_id = _recommend(
        session,
        booking=booking,
        slot=slot,
        scheduling_status=scheduling_status,
        now=calculated_at,
    )

    explanation = _build_explanation(
        is_forecast=is_forecast,
        forecast_detail=forecast_detail,
        farmers_ahead=farmers_ahead,
        average_service_minutes=average_service_minutes,
        estimated_wait_minutes=estimated_wait_minutes,
        estimated_completion_time=estimated_completion_time,
        slot_end_time=slot_end_time,
        overrun_minutes=overrun_minutes,
        booking_status=booking.status,
        scheduling_status=scheduling_status,
        recommendation=recommendation,
        recommended_slot_id=recommended_slot_id,
        recommended_centre_id=recommended_centre_id,
    )

    return SchedulingAssessment(
        booking_id=booking.id,
        centre_id=booking.centre_id,
        slot_id=booking.slot_id,
        scheduling_status=scheduling_status,
        recommendation=recommendation,
        farmers_ahead=farmers_ahead,
        average_service_minutes=average_service_minutes,
        estimated_wait_minutes=estimated_wait_minutes,
        estimated_completion_time=estimated_completion_time,
        slot_end_time=slot_end_time,
        is_forecast=is_forecast,
        recommended_slot_id=recommended_slot_id,
        recommended_centre_id=recommended_centre_id,
        explanation=explanation,
        calculated_at=calculated_at,
    )


def _slot_datetime(slot_date, slot_time) -> datetime:
    """Combine a slot's date and time-of-day into a timezone-aware instant.

    The domain model stores slot dates/times as naive values (there is no
    per-centre timezone in the schema). We treat them as UTC wall-clock
    values so they can be compared against ``calculated_at`` (also UTC),
    consistent with how every other timestamp in this codebase is stored.
    """
    return datetime.combine(slot_date, slot_time, tzinfo=timezone.utc)


def _average_service_minutes(session: Session, centre_id: int) -> Decimal:
    snapshot = throughput_repository.get_latest_snapshot(session, centre_id)
    if snapshot is not None:
        return Decimal(snapshot.avg_minutes_per_farmer)
    # No usable throughput snapshot yet: reuse the ETA service's existing
    # fallback rather than inventing a second default.
    return eta_service.DEFAULT_AVERAGE_SERVICE_MINUTES


@dataclass
class _ForecastEstimate:
    """Breakdown of the slot-anchored forecast for a booking with no live
    QueueEntry yet. Kept separate from SchedulingAssessment so the
    explanation text can cite the intermediate carryover numbers without
    growing the public API response shape."""

    farmers_ahead: int
    estimated_wait_minutes: Decimal
    minutes_until_slot_start: Decimal
    live_queue_count: int
    current_queue_work_minutes: Decimal
    projected_carryover_minutes: Decimal
    ahead_pending_count: int
    ahead_pending_minutes: Decimal


def _forecast_estimate(
    session: Session,
    booking: Booking,
    slot: ProcurementSlot,
    now: datetime,
    average_service_minutes: Decimal,
) -> _ForecastEstimate:
    """Project this booking's completion relative to its own scheduled
    slot, not relative to "right now" - answering "is this slot still on
    track?" rather than "if the farmer walked in this instant, when would
    they finish?"

    Two independent workloads can push the slot late:
      1. Carryover from the *current* live queue: work that is happening
         right now but won't be done by the time this slot starts.
      2. Other pending (not-yet-checked-in) bookings scheduled ahead of
         this one, who are expected to check in and be served before it.

    Carryover step (prototype formula, as specified):
        current_queue_work_minutes = live_queue_count x average_service_minutes
        minutes_until_slot_start   = max(0, slot_start - now)
        projected_carryover_minutes = max(
            0, current_queue_work_minutes - minutes_until_slot_start
        )
    This assumes the live queue keeps draining at the average pace between
    now and slot start; whatever work is left over at that point carries
    into this booking's wait. It deliberately does NOT just dump the whole
    current queue onto a booking that's hours or days away.

    A booking already represented in the live queue is excluded from the
    "pending ahead" count so it is never counted twice (once as queue
    carryover, again as a scheduled booking).
    """
    slot_start = _slot_datetime(slot.slot_date, slot.start_time)

    live_queue = queue_repository.list_live_queue(session, booking.centre_id)
    live_queue_count = len(live_queue)
    live_booking_ids = {entry.booking_id for entry in live_queue}

    current_queue_work_minutes = Decimal(live_queue_count) * average_service_minutes
    minutes_until_slot_start = max(
        Decimal(0), Decimal((slot_start - now).total_seconds()) / Decimal(60)
    )
    projected_carryover_minutes = max(
        Decimal(0), current_queue_work_minutes - minutes_until_slot_start
    )

    pending_bookings = booking_repository.list_pending_bookings_for_centre(
        session, booking.centre_id
    )
    target_key = _slot_sort_key(slot)
    ahead_pending_count = sum(
        1
        for other in pending_bookings
        if other.id != booking.id
        and other.id not in live_booking_ids
        and _slot_sort_key(other.slot) < target_key
    )
    ahead_pending_minutes = Decimal(ahead_pending_count) * average_service_minutes

    workload_at_slot_start_minutes = projected_carryover_minutes + ahead_pending_minutes
    # Total minutes from *now* until the projected completion: the wait
    # until the slot starts, plus whatever workload is still queued up at
    # that point. calculated_at (= now) + this value gives the same
    # anchored completion time as slot_start + workload_at_slot_start.
    estimated_wait_minutes = minutes_until_slot_start + workload_at_slot_start_minutes

    if average_service_minutes > 0:
        carryover_farmers_equiv = int(
            (projected_carryover_minutes / average_service_minutes).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )
    else:
        carryover_farmers_equiv = 0
    farmers_ahead = ahead_pending_count + carryover_farmers_equiv

    return _ForecastEstimate(
        farmers_ahead=farmers_ahead,
        estimated_wait_minutes=estimated_wait_minutes,
        minutes_until_slot_start=minutes_until_slot_start,
        live_queue_count=live_queue_count,
        current_queue_work_minutes=current_queue_work_minutes,
        projected_carryover_minutes=projected_carryover_minutes,
        ahead_pending_count=ahead_pending_count,
        ahead_pending_minutes=ahead_pending_minutes,
    )


def _slot_sort_key(slot: ProcurementSlot) -> tuple:
    return (slot.slot_date, slot.start_time)


# --------------------------------------------------------------------------
# NOTIFY-stage recommendation (Phase 3 only recommends; nothing is sent or
# mutated - actual notification delivery is Phase 4)
# --------------------------------------------------------------------------


def _recommend(
    session: Session,
    *,
    booking: Booking,
    slot: ProcurementSlot,
    scheduling_status: SchedulingStatus,
    now: datetime,
) -> tuple[SchedulingRecommendation, int | None, int | None]:
    if scheduling_status == SchedulingStatus.ON_TRACK:
        return SchedulingRecommendation.KEEP_SLOT, None, None

    if scheduling_status == SchedulingStatus.AT_RISK:
        return SchedulingRecommendation.WARN_FARMER, None, None

    # DELAYED: look for a read-only alternative before falling back to a
    # plain warning. Capacity is never mutated while evaluating these.
    same_centre_slot = _find_later_slot_same_centre(session, booking.centre_id, slot, now)
    if same_centre_slot is not None:
        return (
            SchedulingRecommendation.PROPOSE_NEW_SLOT,
            same_centre_slot.id,
            same_centre_slot.centre_id,
        )

    alternate_centre_slot = _find_alternate_centre_slot(session, booking.centre_id, now)
    if alternate_centre_slot is not None:
        return (
            SchedulingRecommendation.RECOMMEND_ALTERNATE_CENTRE,
            alternate_centre_slot.id,
            alternate_centre_slot.centre_id,
        )

    return SchedulingRecommendation.WARN_FARMER, None, None


def _find_later_slot_same_centre(
    session: Session,
    centre_id: int,
    current_slot: ProcurementSlot,
    now: datetime,
) -> ProcurementSlot | None:
    """Earliest usable slot at the same centre that starts after the
    booking's current slot. Never returns the booking's own slot."""
    current_key = _slot_sort_key(current_slot)
    for candidate in procurement_repository.list_usable_slots(session, centre_id):
        if candidate.id == current_slot.id:
            continue
        if _slot_sort_key(candidate) <= current_key:
            continue
        if _slot_datetime(candidate.slot_date, candidate.end_time) < now:
            continue
        return candidate
    return None


def _find_alternate_centre_slot(
    session: Session,
    exclude_centre_id: int,
    now: datetime,
) -> ProcurementSlot | None:
    """Earliest usable slot, across every other active centre, that hasn't
    already ended. Ties are broken by centre id then slot id for a
    deterministic result."""
    best: tuple[tuple, ProcurementSlot] | None = None
    for centre in procurement_repository.list_active_centres(session):
        if centre.id == exclude_centre_id:
            continue
        for candidate in procurement_repository.list_usable_slots(session, centre.id):
            if _slot_datetime(candidate.slot_date, candidate.end_time) < now:
                continue
            key = (*_slot_sort_key(candidate), centre.id, candidate.id)
            if best is None or key < best[0]:
                best = (key, candidate)
    return best[1] if best is not None else None


# --------------------------------------------------------------------------
# Explanation text
# --------------------------------------------------------------------------


def _build_explanation(
    *,
    is_forecast: bool,
    forecast_detail: _ForecastEstimate | None,
    farmers_ahead: int,
    average_service_minutes: Decimal,
    estimated_wait_minutes: Decimal,
    estimated_completion_time: datetime,
    slot_end_time: datetime,
    overrun_minutes: Decimal,
    booking_status: BookingStatus,
    scheduling_status: SchedulingStatus,
    recommendation: SchedulingRecommendation,
    recommended_slot_id: int | None,
    recommended_centre_id: int | None,
) -> str:
    basis = (
        "Forecast: no live queue entry yet, so this projects from current "
        "centre load and scheduled demand ahead of this booking."
        if is_forecast
        else "Based on this booking's live position in the queue."
    )

    if is_forecast and forecast_detail is not None:
        estimate_line = (
            f"{forecast_detail.live_queue_count} farmer(s) currently in the live "
            f"queue x {average_service_minutes} min/farmer = "
            f"{forecast_detail.current_queue_work_minutes:.2f} min of current queue "
            f"work; the slot starts in {forecast_detail.minutes_until_slot_start:.2f} "
            f"min, leaving {forecast_detail.projected_carryover_minutes:.2f} min of "
            f"carryover work still queued at slot start; plus "
            f"{forecast_detail.ahead_pending_count} pending booking(s) scheduled "
            f"ahead ({forecast_detail.ahead_pending_minutes:.2f} min) = "
            f"{estimated_wait_minutes:.2f} min projected wait from now "
            f"({farmers_ahead} farmer(s)-equivalent ahead), giving an estimated "
            f"completion of {estimated_completion_time.isoformat()} against a slot "
            f"end of {slot_end_time.isoformat()}."
        )
    else:
        estimate_line = (
            f"{farmers_ahead} farmer(s) ahead x {average_service_minutes} min/farmer "
            f"= {estimated_wait_minutes} min estimated wait, giving an estimated "
            f"completion of {estimated_completion_time.isoformat()} against a slot "
            f"end of {slot_end_time.isoformat()}."
        )

    if booking_status == BookingStatus.MISSED:
        classification_line = (
            "Classified DELAYED because the booking's status is already MISSED, "
            "regardless of the numeric estimate."
        )
    elif overrun_minutes <= 0:
        classification_line = (
            f"Classified {scheduling_status.value}: estimated completion is "
            f"{abs(overrun_minutes):.2f} min before the slot end, within the "
            f"{AT_RISK_THRESHOLD_MINUTES}-min ON_TRACK buffer."
        )
    else:
        classification_line = (
            f"Classified {scheduling_status.value}: estimated completion "
            f"overruns the slot end by {overrun_minutes:.2f} min "
            f"(ON_TRACK <= {AT_RISK_THRESHOLD_MINUTES} min, "
            f"AT_RISK <= {DELAYED_THRESHOLD_MINUTES} min, DELAYED beyond that)."
        )

    if recommendation == SchedulingRecommendation.KEEP_SLOT:
        recommendation_line = "Recommendation KEEP_SLOT: booking is on track, no action needed."
    elif recommendation == SchedulingRecommendation.WARN_FARMER:
        if scheduling_status == SchedulingStatus.AT_RISK:
            recommendation_line = (
                "Recommendation WARN_FARMER: within the AT_RISK band, so the "
                "farmer should be warned but no slot change is proposed yet."
            )
        else:
            recommendation_line = (
                "Recommendation WARN_FARMER: booking is DELAYED but no suitable "
                "alternative slot or centre with spare capacity was found."
            )
    elif recommendation == SchedulingRecommendation.PROPOSE_NEW_SLOT:
        recommendation_line = (
            f"Recommendation PROPOSE_NEW_SLOT: booking is DELAYED and a later "
            f"slot (slot_id={recommended_slot_id}) with spare capacity is "
            f"available at the same centre."
        )
    else:
        recommendation_line = (
            f"Recommendation RECOMMEND_ALTERNATE_CENTRE: booking is DELAYED, no "
            f"same-centre alternative was available, but centre_id="
            f"{recommended_centre_id} has a suitable slot (slot_id="
            f"{recommended_slot_id}) with spare capacity."
        )

    return " ".join([basis, estimate_line, classification_line, recommendation_line])
