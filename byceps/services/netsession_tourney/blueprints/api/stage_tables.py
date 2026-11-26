"""
byceps.services.netsession_tourney.blueprints.api.stage_tables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Live tables of group, league and Swiss stages, computed like the website
(`build_ranking_rows`; groups split like `round_robin_groups_display`).
There are no draws in the tournament system. A participant counts as
qualified once it appears in a later stage; when the stage is closed,
everybody else counts as eliminated.
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.site.ranking_helpers import (
    build_ranking_rows,
)
from byceps.services.netsession_tourney.models import StageStatus, StageType

from .match_extras import group_by_stage
from .stage_table_groups import (
    _split_groups,
)


TABLE_STAGE_TYPES = frozenset(
    [StageType.round_robin_groups, StageType.league, StageType.swiss]
)


def build_stage_tables(ranking) -> dict:
    """Map stage ID to a list of groups `{name, standings}` (table stages
    only)."""
    participants_by_id = {p.id: p for p in ranking.participants}
    matches_by_stage_id = group_by_stage(ranking.matches)
    participant_ids_by_stage_id = {
        stage_id: _collect_participant_ids(matches, ranking.slots_by_match_id)
        for stage_id, matches in matches_by_stage_id.items()
    }
    stages = sorted(ranking.stages, key=lambda stage: stage.order_no)

    tables = {}
    for stage in stages:
        if stage.type not in TABLE_STAGE_TYPES:
            continue
        matches = matches_by_stage_id.get(stage.id, [])
        later_ids = _get_later_participant_ids(
            stage, stages, participant_ids_by_stage_id
        )
        groups = _split_groups(stage, matches, ranking.slots_by_match_id)
        tables[stage.id] = [
            {
                'name': name,
                'standings': _build_group_standings(
                    ranking,
                    participants_by_id,
                    participant_ids,
                    group_matches,
                    stage,
                    later_ids,
                ),
            }
            for name, participant_ids, group_matches in groups
        ]
    return tables


def _collect_participant_ids(matches, slots_by_match_id) -> set:
    return {
        slot.participant_id
        for match in matches
        for slot in slots_by_match_id.get(match.id, [])
        if slot.participant_id is not None
    }


def _get_later_participant_ids(
    stage, stages, participant_ids_by_stage_id
) -> set:
    return set().union(
        *(
            participant_ids_by_stage_id.get(other.id, set())
            for other in stages
            if other.order_no > stage.order_no
        )
    )


def _build_group_standings(
    ranking,
    participants_by_id,
    participant_ids,
    group_matches,
    stage,
    later_ids: set,
) -> list[dict]:
    return [
        _serialize_row(row, stage, later_ids)
        for row in build_ranking_rows(
            [
                participants_by_id[pid]
                for pid in participant_ids
                if pid in participants_by_id
            ],
            group_matches,
            {
                m.id: ranking.slots_by_match_id.get(m.id, [])
                for m in group_matches
            },
            ranking.results_by_match_id,
            stage_type=stage.type,
        )
    ]


def _serialize_row(row: dict, stage, later_participant_ids: set) -> dict:
    participant = row['participant']
    if participant.id in later_participant_ids:
        status = 'qualified'
    elif stage.status == StageStatus.closed and later_participant_ids:
        status = 'eliminated'
    else:
        status = None
    return {
        'rank': row.get('rank'),
        'participant_id': str(participant.id),
        'name': participant.name,
        'logo_url': participant.logo_url,
        'played': row.get('played', 0),
        'wins': row.get('wins', 0),
        'draws': 0,
        'losses': row.get('losses', 0),
        'points': row.get('match_points', 0),
        'score_for': row.get('round_wins', 0),
        'score_against': row.get('round_losses', 0),
        'diff': row.get('round_diff', 0),
        'tiebreak': (
            {'buchholz': row.get('buchholz', 0)}
            if stage.type == StageType.swiss
            else {}
        ),
        'status': status,
    }
