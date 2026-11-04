"""
byceps.services.netsession_tourney.ffa_qualifiers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Qualifiers from FFA knockout stages (best placements per match).
"""

from __future__ import annotations

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchID,
    ParticipantID,
)


def _get_ffa_single_elimination_qualifier_ids(
    source_match_id: MatchID,
    source_match_slots: list[DbNetsessionTourneyMatchSlot],
    qualifier_count: int,
) -> list[ParticipantID]:
    if qualifier_count < 1:
        return []

    filled_slots = [
        slot for slot in source_match_slots if slot.participant_id is not None
    ]
    if not filled_slots:
        return []

    db_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=source_match_id)
    )

    placements_by_slot_no: dict[int, int] = {}
    if db_result is not None and isinstance(db_result.ranking_json, dict):
        raw_placements = db_result.ranking_json.get('placements')
        if isinstance(raw_placements, dict):
            for slot in filled_slots:
                raw_value = raw_placements.get(str(slot.slot_no))
                if raw_value is None:
                    raw_value = raw_placements.get(slot.slot_no)
                try:
                    placements_by_slot_no[slot.slot_no] = int(raw_value)
                except (TypeError, ValueError):
                    continue

    sorted_slots = sorted(
        filled_slots,
        key=lambda slot: (
            placements_by_slot_no.get(slot.slot_no, 999_999),
            0
            if db_result is not None and db_result.winner_slot == slot.slot_no
            else 1,
            slot.slot_no,
        ),
    )

    participant_ids = [
        slot.participant_id for slot in sorted_slots if slot.participant_id is not None
    ]
    return participant_ids[:qualifier_count]
