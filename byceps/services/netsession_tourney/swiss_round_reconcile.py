"""
byceps.services.netsession_tourney.swiss_round_reconcile
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Swiss follow-up rounds are created as empty placeholders when the stage is
generated; how many matches a round really needs is only known once the
previous round is played (pairing by record, players floating between
record groups, byes). Before a round is filled, its placeholders are made
to match the real pairing: surplus empty ones are deleted, missing ones
are added, and the match numbers of later rounds are shifted so they stay
consecutive.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete

from byceps.database import db
from byceps.util.uuid import generate_uuid7

from .dbmodels import DbNetsessionTourneyMatch, DbNetsessionTourneyMatchSlot
from .engines.base import MatchSpec
from .models import MatchID, MatchSlotID, MatchState


def reconcile_round_placeholders(
    target_matches: list[DbNetsessionTourneyMatch],
    later_matches: list[DbNetsessionTourneyMatch],
    seeded_specs: list[MatchSpec],
    slots_by_match_id: dict[MatchID, list[DbNetsessionTourneyMatchSlot]],
) -> list[DbNetsessionTourneyMatch]:
    """Return the matches of the round, as many as `seeded_specs`.

    `target_matches` are the empty placeholders of the round (sorted by
    match number), `later_matches` those of all later rounds.
    """
    difference = len(seeded_specs) - len(target_matches)
    if difference == 0:
        return target_matches

    if difference < 0:
        surplus = target_matches[len(seeded_specs) :]
        _delete_matches(surplus, slots_by_match_id)
        _shift_match_numbers(later_matches, difference)
        return target_matches[: len(seeded_specs)]

    _shift_match_numbers(later_matches, difference)
    template = target_matches[0]
    added = [
        _add_placeholder_like(
            template,
            match_no=template.match_no + len(target_matches) + index,
            slots_by_match_id=slots_by_match_id,
        )
        for index in range(difference)
    ]
    return target_matches + added


def _delete_matches(db_matches, slots_by_match_id) -> None:
    match_ids = [db_match.id for db_match in db_matches]
    db.session.execute(
        delete(DbNetsessionTourneyMatchSlot).where(
            DbNetsessionTourneyMatchSlot.match_id.in_(match_ids)
        )
    )
    for db_match in db_matches:
        slots_by_match_id.pop(db_match.id, None)
        db.session.delete(db_match)
    db.session.flush()


def _shift_match_numbers(db_matches, by: int) -> None:
    """Shift match numbers one by one, in an order that never collides
    with the unique (stage, round, match number) constraint."""
    for db_match in sorted(db_matches, key=lambda m: m.match_no, reverse=by > 0):
        db_match.match_no += by
        db.session.flush()


def _add_placeholder_like(
    template: DbNetsessionTourneyMatch,
    *,
    match_no: int,
    slots_by_match_id,
) -> DbNetsessionTourneyMatch:
    db_match = DbNetsessionTourneyMatch(
        MatchID(generate_uuid7()),
        template.tournament_id,
        template.stage_id,
        template.round_no,
        match_no,
        datetime.utcnow(),
        state=MatchState.pending,
        scheduled_at=template.scheduled_at,
        settings_json=dict(template.settings_json or {}),
    )
    db.session.add(db_match)
    db.session.flush()

    slots = [
        DbNetsessionTourneyMatchSlot(MatchSlotID(generate_uuid7()), db_match.id, slot_no)
        for slot_no in (1, 2)
    ]
    for db_slot in slots:
        db.session.add(db_slot)
    db.session.flush()
    slots_by_match_id[db_match.id] = slots
    return db_match
