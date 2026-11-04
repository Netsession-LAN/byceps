"""
byceps.services.netsession_tourney.notification_labels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Match labels used in notifications (e.g. upper/lower bracket wording for double elimination).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchSlot,
)
from .models import (
    MatchID,
    StageID,
)


def _build_double_elimination_notification_match_label(
    db_match: DbNetsessionTourneyMatch,
    stage_id: StageID,
) -> str:
    db_stage_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(stage_id=stage_id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    if not db_stage_matches:
        return f'M #{db_match.match_no}'

    stage_match_ids = [db_stage_match.id for db_stage_match in db_stage_matches]
    db_stage_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter(DbNetsessionTourneyMatchSlot.match_id.in_(stage_match_ids))
        .order_by(
            DbNetsessionTourneyMatchSlot.match_id.asc(),
            DbNetsessionTourneyMatchSlot.slot_no.asc(),
        )
    ).all()

    source_match_id_by_slot_id = {
        db_slot.id: db_slot.match_id for db_slot in db_stage_slots
    }
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]] = (
        defaultdict(list)
    )
    for db_slot in db_stage_slots:
        if db_slot.source_match_slot_id is None:
            continue
        source_match_id = source_match_id_by_slot_id.get(
            db_slot.source_match_slot_id
        )
        if source_match_id is None:
            continue
        incoming_by_match_id[db_slot.match_id].append(
            (source_match_id, db_slot.source_outcome)
        )

    labels_by_match_id = _build_double_elimination_notification_match_labels(
        db_stage_matches,
        incoming_by_match_id,
    )
    return labels_by_match_id.get(db_match.id, f'M #{db_match.match_no}')


def _build_double_elimination_notification_match_labels(
    db_stage_matches: list[DbNetsessionTourneyMatch],
    incoming_by_match_id: dict[MatchID, list[tuple[MatchID, Any]]],
) -> dict[MatchID, str]:
    sorted_matches = sorted(
        db_stage_matches,
        key=lambda match: (match.round_no, match.match_no),
    )
    stage_match_ids = {match.id for match in db_stage_matches}
    bracket_by_match_id: dict[MatchID, str] = {}

    changed = True
    while changed:
        changed = False
        for match in sorted_matches:
            incoming = [
                (source_match_id, outcome)
                for source_match_id, outcome in incoming_by_match_id.get(
                    match.id, []
                )
                if source_match_id in stage_match_ids
            ]
            bracket = bracket_by_match_id.get(match.id)
            next_bracket = bracket
            if not incoming:
                next_bracket = 'WB'
            else:
                source_brackets = {
                    bracket_by_match_id.get(source_match_id)
                    for source_match_id, _ in incoming
                }
                source_brackets.discard(None)

                if 'GF' in source_brackets:
                    next_bracket = 'GF'
                elif any(
                    _is_loser_notification_outcome(outcome)
                    for _, outcome in incoming
                ):
                    next_bracket = 'LB'
                elif source_brackets == {'WB'}:
                    next_bracket = 'WB'
                elif source_brackets == {'LB'}:
                    next_bracket = 'LB'
                elif source_brackets == {'WB', 'LB'}:
                    next_bracket = 'GF'

            if next_bracket != bracket:
                bracket_by_match_id[match.id] = next_bracket
                changed = True

    labels_by_match_id = {match.id: f'M #{match.match_no}' for match in db_stage_matches}

    gf_matches = sorted(
        [
            match
            for match in sorted_matches
            if bracket_by_match_id.get(match.id) == 'GF'
        ],
        key=lambda match: (match.round_no, match.match_no),
    )
    if gf_matches:
        if len(gf_matches) == 1:
            labels_by_match_id[gf_matches[0].id] = 'Grand Final'
        elif len(gf_matches) == 2:
            labels_by_match_id[gf_matches[0].id] = 'Grand Final'
            labels_by_match_id[gf_matches[1].id] = 'Double Grand Final'
        else:
            for index, match in enumerate(gf_matches, start=1):
                labels_by_match_id[match.id] = f'Grand Final #{index}'

    wb_matches = [
        match
        for match in sorted_matches
        if bracket_by_match_id.get(match.id) == 'WB'
    ]
    lb_matches = [
        match
        for match in sorted_matches
        if bracket_by_match_id.get(match.id) == 'LB'
    ]

    labels_by_match_id.update(
        _label_notification_bracket_matches(
            wb_matches,
            prefix='WB',
            semi_prefix='WB Semi',
            final_label='WB Final',
        )
    )
    labels_by_match_id.update(
        _label_notification_bracket_matches(
            lb_matches,
            prefix='LB',
            semi_prefix='LB Semi',
            final_label='LB Final',
        )
    )

    return labels_by_match_id


def _is_loser_notification_outcome(outcome: Any) -> bool:
    value = getattr(outcome, 'value', outcome)
    return value == 'loser'


def _label_notification_bracket_matches(
    matches: list[DbNetsessionTourneyMatch],
    *,
    prefix: str,
    semi_prefix: str,
    final_label: str,
) -> dict[MatchID, str]:
    if not matches:
        return {}

    labels_by_match_id: dict[MatchID, str] = {}
    matches_by_round_no: dict[int, list[DbNetsessionTourneyMatch]] = (
        defaultdict(list)
    )
    for match in matches:
        matches_by_round_no[match.round_no].append(match)

    sorted_round_nos = sorted(matches_by_round_no.keys())
    final_round_no = sorted_round_nos[-1]
    final_round_matches = sorted(
        matches_by_round_no[final_round_no],
        key=lambda match: match.match_no,
    )
    for index, match in enumerate(final_round_matches, start=1):
        labels_by_match_id[match.id] = (
            final_label
            if len(final_round_matches) == 1
            else f'{final_label} #{index}'
        )

    semi_round_no = sorted_round_nos[-2] if len(sorted_round_nos) >= 2 else None
    if semi_round_no is not None:
        semi_matches = sorted(
            matches_by_round_no[semi_round_no],
            key=lambda match: match.match_no,
        )
        for index, match in enumerate(semi_matches, start=1):
            labels_by_match_id[match.id] = f'{semi_prefix} #{index}'

    running_no = 1
    for round_no in sorted_round_nos:
        for match in sorted(
            matches_by_round_no[round_no],
            key=lambda current_match: current_match.match_no,
        ):
            if match.id in labels_by_match_id:
                continue
            labels_by_match_id[match.id] = f'{prefix} #{running_no}'
            running_no += 1

    return labels_by_match_id
