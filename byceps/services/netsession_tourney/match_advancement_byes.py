"""
byceps.services.netsession_tourney.match_advancement_byes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Finding bye matches that can be advanced automatically.
"""

from __future__ import annotations

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchState,
    ParticipantID,
)


# winner slot number, winner participant ID, whether the match is empty
_Bye = tuple[int | None, ParticipantID | None, bool]


def _find_bye(db_slots: list[DbNetsessionTourneyMatchSlot]) -> _Bye | None:
    """Return the outcome of the match if it is a bye, else `None`."""
    filled_slots = [slot for slot in db_slots if slot.participant_id]
    has_any_source_slots = any(
        slot.source_match_slot_id is not None for slot in db_slots
    )
    # Auto-advance only hard byes, not unresolved feeder slots.
    # A feeder slot with no participant is considered resolved if the
    # source match is already completed and produced no winner/loser
    # for that outcome path (e.g. loser path from a bye match).
    if _has_unresolved_source_slots(db_slots):
        return None

    return _pick_bye_winner(filled_slots, has_any_source_slots)


def _has_unresolved_source_slots(
    db_slots: list[DbNetsessionTourneyMatchSlot],
) -> bool:
    unresolved_source_slots = [
        slot for slot in db_slots if _is_unresolved_source_slot(slot)
    ]
    return bool(unresolved_source_slots)


def _pick_bye_winner(
    filled_slots: list[DbNetsessionTourneyMatchSlot],
    has_any_source_slots: bool,
) -> _Bye | None:
    if len(filled_slots) == 1:
        return filled_slots[0].slot_no, filled_slots[0].participant_id, False

    # Propagate an explicitly empty feeder path (e.g. LB branch fed
    # only by bye matches), but never consume pre-created placeholder
    # matches that do not have resolved feeder sources yet.
    if len(filled_slots) == 0 and has_any_source_slots:
        return None, None, True

    return None


def _is_unresolved_source_slot(slot: DbNetsessionTourneyMatchSlot) -> bool:
    """Tell whether the slot is an empty feeder slot whose source match is
    missing or not completed yet."""
    return (
        slot.participant_id is None
        and slot.source_match_slot_id is not None
        and (
            (
                source_slot := db.session.get(
                    DbNetsessionTourneyMatchSlot,
                    slot.source_match_slot_id,
                )
            )
            is None
            or (
                source_match := db.session.get(
                    DbNetsessionTourneyMatch, source_slot.match_id
                )
            )
            is None
            or source_match.state != MatchState.completed.value
        )
    )
