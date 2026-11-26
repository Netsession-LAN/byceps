"""
byceps.services.netsession_tourney.blueprints.site.stage_filters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from byceps.services.netsession_tourney.models import StageType


def _is_ffa_simple_stage(stage) -> bool:
    return stage is not None and stage.type == StageType.ffa_simple


def _is_ffa_scoring_stage(stage) -> bool:
    return stage is not None and stage.type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
    }


def _is_flatout2_stage(stage) -> bool:
    return (
        stage is not None
        and stage.type == StageType.ffa_flatout2_single_elimination
    )


def is_ffa_single_elimination_stage(stage) -> bool:
    return stage is not None and stage.type in {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }


def _is_swiss_stage(stage) -> bool:
    return stage is not None and stage.type == StageType.swiss


def _is_round_based_duel_stage(stage) -> bool:
    return stage is not None and stage.type in {
        StageType.swiss,
        StageType.round_robin_groups,
        StageType.league,
    }


def _get_match_stages(stages_by_id, match_stage_ids) -> list:
    return [
        stages_by_id[stage_id]
        for stage_id in match_stage_ids
        if stage_id in stages_by_id
    ]


def _get_relevant_stages(stages, matches) -> list:
    if not stages:
        return []

    stages_by_id = {stage.id: stage for stage in stages}
    match_stage_ids = {match.stage_id for match in matches}
    if not match_stage_ids:
        return list(stages)

    return _get_match_stages(stages_by_id, match_stage_ids)


def _uses_only_stages_matching(stages, matches, predicate) -> bool:
    relevant_stages = _get_relevant_stages(stages, matches)
    if not relevant_stages:
        return False

    return all(predicate(stage) for stage in relevant_stages)


def uses_only_ffa_simple_stages(stages, matches) -> bool:
    return _uses_only_stages_matching(stages, matches, _is_ffa_simple_stage)


def uses_only_ffa_scoring_stages(stages, matches) -> bool:
    return _uses_only_stages_matching(stages, matches, _is_ffa_scoring_stage)


def uses_only_flatout2_stages(stages, matches) -> bool:
    return _uses_only_stages_matching(stages, matches, _is_flatout2_stage)


def uses_only_ffa_single_elimination_stages(stages, matches) -> bool:
    return _uses_only_stages_matching(
        stages, matches, is_ffa_single_elimination_stage
    )


def uses_only_swiss_stages(stages, matches) -> bool:
    return _uses_only_stages_matching(stages, matches, _is_swiss_stage)


def uses_only_round_based_duel_stages(stages, matches) -> bool:
    return _uses_only_stages_matching(
        stages, matches, _is_round_based_duel_stage
    )
