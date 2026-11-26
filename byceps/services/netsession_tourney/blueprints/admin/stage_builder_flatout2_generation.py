"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

State of the stage generation form, including the manual
FlatOut 2 configuration.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_config import (
    parse_flatout2_round_configuration,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_form import (
    build_flatout2_participant_choices,
    build_flatout2_round_defaults_by_no,
    FLATOUT2_MAX_MATCH_COUNT_PER_ROUND,
    get_dict_setting,
    get_flatout2_max_players_per_match,
    get_list_setting,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_round_state import (
    build_flatout2_round_state,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_helpers import (
    get_stage_generation_block_reason,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_display import (
    is_builder_main_stage_with_preliminary_source,
)
from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_MAX_RACES_PER_ROUND,
    FLATOUT2_MODE_CHOICES,
    FLATOUT2_TRACK_CHOICES_BY_MODE,
    FLATOUT2_VEHICLE_CHOICES_BY_MODE,
)
from byceps.services.netsession_tourney.models import (
    Match,
    Stage,
    StageID,
    StageType,
)
from byceps.util.result import Err, Ok, Result


def is_flatout2_stage_type(stage_type: StageType | None) -> bool:
    return stage_type == StageType.ffa_flatout2_single_elimination


def _get_flatout2_total_round_count(stage: Stage) -> int | None:
    round_count = _count_flatout2_configured_rounds(stage)
    if round_count > 0:
        return round_count

    try:
        round_count = int((stage.settings or {}).get('round_count') or 0)
    except TypeError, ValueError:
        return None

    return round_count if round_count > 0 else None


def _count_flatout2_configured_rounds(stage: Stage) -> int:
    raw_rounds = (stage.settings or {}).get('flatout2_rounds')
    if not isinstance(raw_rounds, list):
        return 0

    return len(
        [raw_round for raw_round in raw_rounds if isinstance(raw_round, dict)]
    )


def _get_flatout2_generation_action_label(
    stage_matches: list[Match],
) -> str:
    return (
        gettext('Phase neu vorbereiten')
        if stage_matches
        else gettext('Phase vorbereiten')
    )


def build_stage_generation_state(
    stage: Stage,
    stages_by_id: dict[StageID, Stage],
    matches_by_stage: dict[StageID, list[Match]],
) -> dict:
    block_reason = get_stage_generation_block_reason(
        stage,
        stages_by_id,
        matches_by_stage,
    )
    action_label = gettext('Setzliste / Matches generieren')
    action_hint = None

    if is_flatout2_stage_type(stage.type):
        stage_matches = sorted(
            matches_by_stage.get(stage.id, []),
            key=lambda match: (match.round_no, match.match_no),
        )
        total_round_count = _get_flatout2_total_round_count(stage)
        action_label = _get_flatout2_generation_action_label(stage_matches)
        if total_round_count == 1:
            action_hint = gettext(
                'Diese FlatOut-2-Phase besteht aus einem einzelnen Finale und wird komplett manuell vorbereitet.'
            )
        elif total_round_count is not None and total_round_count > 1:
            action_hint = gettext(
                'Konfiguriert: %(count)s Runden. Diese FlatOut-2-Phase wird komplett manuell vorbereitet und bei Bedarf neu erzeugt.',
                count=total_round_count,
            )
        else:
            action_hint = gettext(
                'Diese FlatOut-2-Phase wird komplett manuell vorbereitet. Lege Runden, Matches, Rennen, Hosts und Teilnehmer direkt in der Phase fest.'
            )

    return {
        'block_reason': block_reason,
        'locks_manual_seeding': is_builder_main_stage_with_preliminary_source(
            stage
        ),
        'action_label': action_label,
        'action_hint': action_hint,
    }


def build_flatout2_generation_state(
    stage,
    *,
    participants: list,
    posted_form=None,
) -> dict:
    existing_stage_settings = stage.settings or {}
    raw_rounds = get_list_setting(existing_stage_settings, 'flatout2_rounds')
    raw_match_blueprints = get_dict_setting(
        existing_stage_settings, 'flatout2_match_blueprints'
    )
    max_players_per_match = get_flatout2_max_players_per_match(
        existing_stage_settings
    )

    participant_choices = build_flatout2_participant_choices(participants)
    participant_choice_values = {
        choice['value'] for choice in participant_choices
    }
    max_match_count_per_round = FLATOUT2_MAX_MATCH_COUNT_PER_ROUND
    round_defaults_by_no = build_flatout2_round_defaults_by_no(raw_rounds)

    rounds = [
        build_flatout2_round_state(
            stage,
            round_no,
            default_round=round_defaults_by_no.get(round_no, {}),
            raw_match_blueprints=raw_match_blueprints,
            posted_form=posted_form,
            max_players_per_match=max_players_per_match,
            participant_choice_values=participant_choice_values,
        )
        for round_no in (1,)
    ]

    return {
        'round_count': 1,
        'rounds': rounds,
        'participant_choices': participant_choices,
        'mode_choices': FLATOUT2_MODE_CHOICES,
        'track_choices_by_mode': FLATOUT2_TRACK_CHOICES_BY_MODE,
        'vehicle_choices_by_mode': FLATOUT2_VEHICLE_CHOICES_BY_MODE,
        'race_count_choices': list(range(1, FLATOUT2_MAX_RACES_PER_ROUND + 1)),
        'round_count_choices': [1],
        'match_count_choices': list(range(1, max_match_count_per_round + 1)),
        'max_players_per_match': max_players_per_match,
    }


def parse_flatout2_generation_configuration(
    stage,
    participants,
    request_form,
) -> Result[tuple[dict, dict[tuple[int, int], dict]], str]:
    participant_ids_by_str = {
        str(participant.id): participant.id for participant in participants
    }
    max_players_per_match = get_flatout2_max_players_per_match(
        stage.settings or {}
    )
    round_count = 1

    rounds = []
    match_blueprints: dict[str, dict] = {}
    match_settings_by_round_and_match_no: dict[tuple[int, int], dict] = {}

    for round_no in (1,):
        round_result = parse_flatout2_round_configuration(
            stage,
            round_no,
            request_form,
            participant_ids_by_str,
            max_players_per_match,
        )
        if round_result.is_err():
            return Err(round_result.unwrap_err())

        round_configuration, round_match_blueprints, round_match_settings = (
            round_result.unwrap()
        )
        rounds.append(round_configuration)
        match_blueprints.update(round_match_blueprints)
        match_settings_by_round_and_match_no.update(round_match_settings)

    return Ok(
        (
            {
                'flatout2_manual_stage': True,
                'round_count': round_count,
                'flatout2_rounds': rounds,
                'flatout2_match_blueprints': match_blueprints,
            },
            match_settings_by_round_and_match_no,
        )
    )
