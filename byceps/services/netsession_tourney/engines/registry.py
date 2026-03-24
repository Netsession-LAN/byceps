"""
byceps.services.netsession_tourney.engines.registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from .base import StageEngine
from .implementations import (
    get_bracket_groups_engine,
    get_double_elimination_engine,
    get_double_elimination_with_double_grand_final_engine,
    get_custom_bracket_engine,
    get_ffa_bracket_groups_engine,
    get_ffa_custom_bracket_engine,
    get_ffa_league_engine,
    get_ffa_single_elimination_engine,
    get_ffa_simple_engine,
    get_flatout2_single_elimination_engine,
    get_gauntlet_engine,
    get_league_engine,
    get_round_robin_groups_engine,
    get_single_elimination_engine,
    get_swiss_engine,
)
from ..models import StageFamily, StageType, StageTypeSpec


_STAGE_TYPE_SPECS = {
    StageType.single_elimination: StageTypeSpec(
        type=StageType.single_elimination,
        family=StageFamily.duel,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.double_elimination: StageTypeSpec(
        type=StageType.double_elimination,
        family=StageFamily.duel,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.double_elimination_double_grand_final: StageTypeSpec(
        type=StageType.double_elimination_double_grand_final,
        family=StageFamily.duel,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.gauntlet: StageTypeSpec(
        type=StageType.gauntlet,
        family=StageFamily.duel,
        enabled=False,
        beta=False,
        publishable=True,
    ),
    StageType.bracket_groups: StageTypeSpec(
        type=StageType.bracket_groups,
        family=StageFamily.duel,
        enabled=False,
        beta=False,
        publishable=True,
    ),
    StageType.custom_bracket: StageTypeSpec(
        type=StageType.custom_bracket,
        family=StageFamily.duel,
        enabled=False,
        beta=False,
        publishable=True,
    ),
    StageType.round_robin_groups: StageTypeSpec(
        type=StageType.round_robin_groups,
        family=StageFamily.duel,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.league: StageTypeSpec(
        type=StageType.league,
        family=StageFamily.duel,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.swiss: StageTypeSpec(
        type=StageType.swiss,
        family=StageFamily.duel,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.ffa_simple: StageTypeSpec(
        type=StageType.ffa_simple,
        family=StageFamily.ffa,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.ffa_single_elimination: StageTypeSpec(
        type=StageType.ffa_single_elimination,
        family=StageFamily.ffa,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.ffa_flatout2_single_elimination: StageTypeSpec(
        type=StageType.ffa_flatout2_single_elimination,
        family=StageFamily.ffa,
        enabled=True,
        beta=False,
        publishable=True,
    ),
    StageType.ffa_bracket_groups: StageTypeSpec(
        type=StageType.ffa_bracket_groups,
        family=StageFamily.ffa,
        enabled=False,
        beta=False,
        publishable=True,
    ),
    StageType.ffa_league: StageTypeSpec(
        type=StageType.ffa_league,
        family=StageFamily.ffa,
        enabled=False,
        beta=False,
        publishable=True,
    ),
    StageType.ffa_custom_bracket: StageTypeSpec(
        type=StageType.ffa_custom_bracket,
        family=StageFamily.ffa,
        enabled=False,
        beta=False,
        publishable=True,
    ),
}


_ENGINES = {
    StageType.single_elimination: get_single_elimination_engine(),
    StageType.double_elimination: get_double_elimination_engine(),
    StageType.double_elimination_double_grand_final: (
        get_double_elimination_with_double_grand_final_engine()
    ),
    StageType.gauntlet: get_gauntlet_engine(),
    StageType.bracket_groups: get_bracket_groups_engine(),
    StageType.custom_bracket: get_custom_bracket_engine(),
    StageType.round_robin_groups: get_round_robin_groups_engine(),
    StageType.league: get_league_engine(),
    StageType.swiss: get_swiss_engine(),
    StageType.ffa_simple: get_ffa_simple_engine(),
    StageType.ffa_single_elimination: get_ffa_single_elimination_engine(),
    StageType.ffa_flatout2_single_elimination: (
        get_flatout2_single_elimination_engine()
    ),
    StageType.ffa_bracket_groups: get_ffa_bracket_groups_engine(),
    StageType.ffa_league: get_ffa_league_engine(),
    StageType.ffa_custom_bracket: get_ffa_custom_bracket_engine(),
}


def get_stage_type_specs() -> list[StageTypeSpec]:
    return [spec for _, spec in sorted(_STAGE_TYPE_SPECS.items(), key=lambda item: item[0].value)]


def get_stage_type_spec(stage_type: StageType) -> StageTypeSpec:
    return _STAGE_TYPE_SPECS[stage_type]


def find_stage_engine(stage_type: StageType) -> StageEngine | None:
    return _ENGINES.get(stage_type)
