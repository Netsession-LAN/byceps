"""
byceps.services.netsession_tourney.blueprints.api.match_extras_advancing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Per-stage grouping of matches and the participants that advanced from each completed match.
"""

from __future__ import annotations

from collections import defaultdict

from byceps.services.netsession_tourney.models import MatchState


def group_by_stage(matches) -> dict:
    by_stage = defaultdict(list)
    for match in matches:
        by_stage[match.stage_id].append(match)
    return by_stage


def build_advancing_ids_by_match_id(ranking) -> dict:
    """For completed matches of FFA stages: the participants that play in a
    later round or stage. Other matches are left out (no such notion)."""
    order_by_stage_id = {stage.id: stage.order_no for stage in ranking.stages}
    ffa_stage_ids = {
        stage.id
        for stage in ranking.stages
        if stage.type.value.startswith('ffa')
    }

    advancing = {}
    for match in ranking.matches:
        if not _is_completed_match_in(match, ffa_stage_ids):
            continue
        later_ids = _get_later_participant_ids(
            ranking, match, order_by_stage_id
        )
        advancing[match.id] = _get_participant_ids(ranking, match) & later_ids
    return advancing


def _is_completed_match_in(match, stage_ids: set) -> bool:
    if match.stage_id not in stage_ids:
        return False
    return match.state == MatchState.completed


def _get_later_participant_ids(ranking, match, order_by_stage_id) -> set:
    match_position = _get_position(match, order_by_stage_id)
    return set().union(
        *(
            _get_participant_ids(ranking, other)
            for other in ranking.matches
            if _get_position(other, order_by_stage_id) > match_position
        )
    )


def _get_position(match, order_by_stage_id) -> tuple:
    return (order_by_stage_id.get(match.stage_id, 0), match.round_no)


def _get_participant_ids(ranking, match) -> set:
    return {
        slot.participant_id
        for slot in ranking.slots_by_match_id.get(match.id, [])
        if slot.participant_id is not None
    }
