"""Procurement/scheduling integration adapter for reference data.

This is the ONLY module that bridges the reference-data layer
(``app/repositories/reference.py``, ``app/services/reference_data.py``)
with the operational procurement domain (``ProcurementCentre``). It exists
so that nothing in ``app/services/scheduling.py``, ``eta.py``,
``throughput.py``, ``queue.py``, or ``bookings.py`` needs to import the
reference-data layer at all:

    reference repository -> reference service -> (this module) -> API

The boundary is intentional and load-bearing, not incidental: since this
module is never imported by the scheduling engine, a reference-data
problem (missing table, malformed row, unexpected query error) can
structurally never affect a scheduling/ETA/queue/booking decision - there
is no code path connecting them. This module is only ever called directly
from the API layer (see ``app/api/routers/centres.py``).

Design decisions (see the Milestone 2 write-up for the full reasoning):

- The only field the operational schema and the reference-data schema
  genuinely share is ``district`` (``ProcurementCentre.district`` /
  ``ReferenceDataset.district``). There is no ``season_or_period``,
  ``dataset_type``, or controlled crop vocabulary anywhere in the
  operational schema, so this module does not invent a mapping from
  ``Booking.crop_type`` (free text) to a reference ``metric_name`` - doing
  so would be a fabricated heuristic, not a fact drawn from the data.
- No numeric signal, score, or priority is derived from a reference
  metric's value. The one real dataset available at this milestone
  (district paddy area, in lakh hectares) has no defensible deterministic
  relationship to queue wait time or scheduling status, so deriving a
  "priority" from it would be inventing a correlation the data doesn't
  support. This module is a context/enrichment lookup only.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories import procurement as procurement_repository
from app.services import reference_data as reference_service


class ProcurementContextError(Exception):
    """Raised only for a genuinely invalid request (e.g. an unknown centre
    id) - never for the ordinary, expected absence of matching reference
    data. Mirrors the shape of ``scheduling.SchedulingError``."""

    def __init__(self, detail: str, status_code: int) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class CentreAgriculturalContext:
    """The agricultural reference context available for one procurement
    centre's district, plus enough identifying detail to make clear what
    it does and does not cover.

    ``reference_facts`` is empty - not ``None``, not an error - whenever
    no reference data matches yet. That is the normal state for a
    district that hasn't had anything imported for it, or for filters
    that don't match anything currently on file.
    """

    centre_id: int
    district: str
    reference_facts: list[reference_service.ReferenceContext]


def get_centre_agricultural_context(
    session: Session,
    centre_id: int,
    *,
    dataset_type: str | None = None,
    metric_name: str | None = None,
    season_or_period: str | None = None,
) -> CentreAgriculturalContext:
    """Look up the reference facts available for a procurement centre's
    district.

    Raises ``ProcurementContextError(..., 404)`` only when ``centre_id``
    itself doesn't exist - a genuine bad request. A valid centre whose
    district has no matching reference data (yet, or ever, or for the
    given filters) is not an error: it returns a
    ``CentreAgriculturalContext`` with an empty ``reference_facts`` list,
    so the existing procurement/booking/scheduling flows this centre
    participates in are never affected by whether reference data happens
    to exist for it.
    """
    centre = procurement_repository.get_centre(session, centre_id)
    if centre is None:
        raise ProcurementContextError("Procurement centre not found", 404)

    reference_facts = reference_service.find_reference_context(
        session,
        district=centre.district,
        dataset_type=dataset_type,
        metric_name=metric_name,
        season_or_period=season_or_period,
    )

    return CentreAgriculturalContext(
        centre_id=centre.id,
        district=centre.district,
        reference_facts=reference_facts,
    )
