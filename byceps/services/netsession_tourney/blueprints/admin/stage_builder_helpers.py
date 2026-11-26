"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

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
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_placement_points import (
    get_first_positive_int,
    get_max_rule_place,
    parse_ffa_placement_points_text,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_review_lines import (
    build_review_preview_lines,
    parse_review_plan_arguments,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_summary_lines import (
    build_preliminary_generation_summary_lines,
    build_stage_builder_role_meta,
    format_group_distribution_summary,
    get_main_generation_summary_line,
    get_round_robin_builder_mode,
)
from byceps.services.netsession_tourney.blueprints.site.builder_helpers import (
    get_builder_container_child_stage_ids,
)
from byceps.services.netsession_tourney.engines.bracket_helpers import (
    distribute_evenly,
)
from byceps.services.netsession_tourney.flatout2 import (
    FLATOUT2_MAX_RACES_PER_ROUND,
    FLATOUT2_MODE_CHOICES,
    FLATOUT2_TRACK_CHOICES_BY_MODE,
    FLATOUT2_VEHICLE_CHOICES_BY_MODE,
)
from byceps.services.netsession_tourney.forms import (
    StageBuilderMainForm,
    StageBuilderPreliminaryForm,
    StageBuilderTimingForm,
    StageForm,
)
from byceps.services.netsession_tourney.generation_guard import (
    check_generation_allowed_for_stage,
)
from byceps.services.netsession_tourney.generation_participants import (
    is_builder_preliminary_skipped,
)
from byceps.services.netsession_tourney.models import (
    Match,
    MatchState,
    ParticipantID,
    Stage,
    StageID,
    StageType,
    TournamentID,
    TournamentMode,
)
from byceps.services.netsession_tourney.result_report_mode import (
    RESULT_REPORT_MODE_ADMIN_ONLY,
)
from byceps.services.netsession_tourney.score_parsing import (
    get_ffa_points_per_kill,
)
from byceps.services.netsession_tourney.stage_builder_preview import (
    preview_stage_builder_plan,
)
from byceps.services.netsession_tourney.stage_builder_settings import (
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)
from byceps.services.netsession_tourney.stage_generation import (
    preview_stage_match_generation,
)
from byceps.services.netsession_tourney.stage_service import (
    parse_source_stage_ids,
)
from byceps.services.netsession_tourney.swiss_thresholds import (
    get_configured_swiss_threshold,
    get_swiss_round_count_for_threshold,
    get_swiss_threshold_for_round_count,
)
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.party.models import Party, PartyID
from byceps.util.framework.flash import flash_error
from byceps.util.result import Err, Ok, Result
from byceps.util.views import redirect_to


def is_stage_builder_main_complete(state: dict) -> bool:
    if not all(
        (
            state.get('generation_basis'),
            state.get('main_stage_type'),
            state.get('main_stage_size'),
        )
    ):
        return False

    if state.get('main_stage_type') in {
        StageType.ffa_single_elimination.value,
        StageType.ffa_flatout2_single_elimination.value,
    }:
        return state.get('max_players_per_match') is not None

    return bool(state.get('main_stage_size'))


def is_stage_builder_preliminary_complete(state: dict) -> bool:
    if 'use_preliminary' not in state:
        return False

    if not state.get('use_preliminary'):
        return True

    preliminary_type = state.get('preliminary_type')
    if not preliminary_type:
        return False

    if (
        preliminary_type == StageType.round_robin_groups.value
        and state.get('round_robin_builder_mode') == 'manual_group_count'
    ):
        return state.get('round_robin_group_count') is not None

    if preliminary_type != StageType.swiss.value:
        return True

    return state.get('swiss_threshold') is not None


def is_ffa_stage_builder_tournament(tournament) -> bool:
    return tournament.mode == TournamentMode.ffa


def get_stage_builder_default_main_stage_size(tournament) -> str:
    participant_limit = tournament.participant_limit
    if participant_limit is not None:
        for allowed_size in sorted(STAGE_BUILDER_MAIN_STAGE_SIZES):
            if allowed_size >= participant_limit:
                return str(allowed_size)

    return '64'  # no limit set: a sensible start, the admin adjusts it


def is_stage_builder_timing_complete(state: dict) -> bool:
    return 'break_between_rounds_minutes' in state


def stage_to_form_data(stage) -> dict:
    result_report_mode = stage.settings.get(
        'result_report_mode', 'both_must_confirm'
    )
    if _is_ffa_scoring_stage_type(stage.type):
        result_report_mode = RESULT_REPORT_MODE_ADMIN_ONLY

    swiss_threshold = get_configured_swiss_threshold(stage.settings)
    if swiss_threshold is None and stage.type == StageType.swiss:
        raw_round_count = stage.settings.get('round_count')
        try:
            swiss_threshold = get_swiss_threshold_for_round_count(
                int(raw_round_count)
            )
        except TypeError, ValueError:
            swiss_threshold = None
    if swiss_threshold not in {2, 3, 4}:
        swiss_threshold = None

    return {
        'type': stage.type.value,
        'name': stage.name,
        'round_count': stage.settings.get('round_count'),
        'swiss_threshold': swiss_threshold,
        'max_players_per_match': stage.settings.get('max_players_per_match'),
        'group_size': stage.settings.get('group_size'),
        'placement_points': _format_ffa_placement_points_rules(
            stage.settings.get('placement_points_rules')
        ),
        'points_per_kill': get_ffa_points_per_kill(stage.settings),
        'match_duration_minutes': stage.settings.get('match_duration_minutes'),
        'max_matches_per_round': stage.settings.get('max_matches_per_round'),
        'break_between_rounds_minutes': stage.settings.get(
            'break_between_rounds_minutes'
        ),
        'result_report_mode': result_report_mode,
    }


def _format_ffa_placement_points_rules(rules) -> str:
    if not isinstance(rules, list):
        return ''

    normalized_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue

        try:
            from_place = int(rule.get('from_place'))
            to_place = int(rule.get('to_place'))
            points = int(rule.get('points'))
        except TypeError, ValueError:
            continue

        normalized_rules.append((from_place, to_place, points))

    normalized_rules.sort(key=lambda item: (item[0], item[1], -item[2]))

    lines = []
    for from_place, to_place, points in normalized_rules:
        place_label = (
            str(from_place)
            if from_place == to_place
            else f'{from_place}-{to_place}'
        )
        lines.append(f'{place_label} = {points}')

    return '\n'.join(lines)


def _is_ffa_scoring_stage_type(stage_type: StageType | None) -> bool:
    return stage_type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
    }


def is_ffa_result_stage_type(stage_type: StageType | None) -> bool:
    return stage_type in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }


def get_ffa_placement_points_row_count(
    tournament,
    placement_points_text: str | None,
    *,
    stage_type: StageType | None = None,
    max_players_per_match: int | None = None,
    existing_settings: dict | None = None,
) -> int:
    if stage_type == StageType.ffa_single_elimination:
        parsed = get_first_positive_int(
            _get_max_players_per_match_candidates(
                max_players_per_match, existing_settings
            )
        )
        if parsed is not None:
            return parsed

    participant_limit = getattr(tournament, 'participant_limit', None)
    if (
        stage_type != StageType.ffa_single_elimination
        and isinstance(participant_limit, int)
        and participant_limit > 0
    ):
        return participant_limit

    return get_max_rule_place(placement_points_text)


def _get_max_players_per_match_candidates(
    max_players_per_match: int | None, existing_settings: dict | None
) -> list:
    candidates = [max_players_per_match]
    if isinstance(existing_settings, dict):
        candidates.append(existing_settings.get('max_players_per_match'))
    return candidates


def stage_settings_from_form(
    form: StageForm, *, existing_settings: dict | None = None
) -> Result[dict, str]:
    stage_type = _parse_stage_type(form.type.data)

    settings = {}
    if stage_type == StageType.swiss and form.swiss_threshold.data is None:
        return Err(gettext('Bitte eine Swiss-Schwelle auswählen.'))

    _add_round_settings(settings, form, stage_type)
    _add_match_size_settings(settings, form, stage_type)
    if _is_ffa_scoring_stage_type(stage_type):
        parsed_rules_result = parse_ffa_placement_points_text(
            form.placement_points.data
        )
        if parsed_rules_result.is_err():
            return Err(parsed_rules_result.unwrap_err())

        _add_ffa_scoring_settings(settings, form, parsed_rules_result.unwrap())
    _add_timing_settings(settings, form, stage_type)
    settings['result_report_mode'] = _get_result_report_mode(form, stage_type)

    if existing_settings is not None:
        _copy_participant_source_settings(settings, existing_settings)

    return Ok(settings)


def _parse_stage_type(raw_stage_type) -> StageType | None:
    try:
        return StageType(raw_stage_type)
    except ValueError:
        return None


def _add_round_settings(
    settings: dict, form: StageForm, stage_type: StageType | None
) -> None:
    if form.round_count.data and stage_type != StageType.swiss:
        settings['round_count'] = form.round_count.data
    if stage_type == StageType.swiss and form.swiss_threshold.data:
        settings['swiss_threshold'] = form.swiss_threshold.data
        settings['round_count'] = get_swiss_round_count_for_threshold(
            form.swiss_threshold.data
        )


def _add_match_size_settings(
    settings: dict, form: StageForm, stage_type: StageType | None
) -> None:
    if form.max_players_per_match.data and stage_type != StageType.ffa_simple:
        settings['max_players_per_match'] = form.max_players_per_match.data
    if form.group_size.data:
        settings['group_size'] = form.group_size.data


def _add_ffa_scoring_settings(
    settings: dict, form: StageForm, placement_points_rules: list[dict]
) -> None:
    settings['placement_points_rules'] = placement_points_rules
    settings['points_per_kill'] = (
        form.points_per_kill.data
        if form.points_per_kill.data is not None
        else 1
    )


def _add_timing_settings(
    settings: dict, form: StageForm, stage_type: StageType | None
) -> None:
    if form.match_duration_minutes.data:
        settings['match_duration_minutes'] = form.match_duration_minutes.data
    if form.max_matches_per_round.data and stage_type not in {
        StageType.ffa_simple,
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }:
        settings['max_matches_per_round'] = form.max_matches_per_round.data
    if form.break_between_rounds_minutes.data is not None:
        settings['break_between_rounds_minutes'] = (
            form.break_between_rounds_minutes.data
        )


def _get_result_report_mode(
    form: StageForm, stage_type: StageType | None
) -> str:
    return (
        RESULT_REPORT_MODE_ADMIN_ONLY
        if is_ffa_result_stage_type(stage_type)
        else (form.result_report_mode.data or 'both_must_confirm')
    )


def _copy_participant_source_settings(
    settings: dict, existing_settings: dict
) -> None:
    for key in (
        'participant_source_mode',
        'qualifier_source_stage_ids',
        'qualifier_top_n',
    ):
        if key in existing_settings:
            settings[key] = existing_settings[key]


def participant_source_settings_from_form(
    request_form, *, eligible_source_stages
):
    mode = (request_form.get('participant_source_mode') or 'tournament').strip()
    if mode not in {'tournament', 'stage_qualifiers'}:
        return Err(gettext('Ungültige Teilnehmerquelle.'))

    settings = {'participant_source_mode': mode}

    if mode != 'stage_qualifiers':
        return Ok(settings)

    qualifier_settings_result = _parse_stage_qualifier_settings(
        request_form, eligible_source_stages
    )
    if qualifier_settings_result.is_err():
        return Err(qualifier_settings_result.unwrap_err())

    settings.update(qualifier_settings_result.unwrap())
    return Ok(settings)


def _parse_stage_qualifier_settings(
    request_form, eligible_source_stages
) -> Result[dict, str]:
    qualifier_selection_mode = (
        request_form.get('qualifier_selection_mode') or 'per_stage'
    ).strip()
    if qualifier_selection_mode not in {'per_stage', 'per_group'}:
        return Err(gettext('Ungültiger Qualifikationsmodus.'))

    selected_source_stage_ids = _parse_selected_source_stage_ids(
        request_form, eligible_source_stages
    )
    if not selected_source_stage_ids:
        return Err(
            gettext(
                'Bitte mindestens eine vorherige Phase als Quelle auswählen.'
            )
        )

    qualifier_top_n_result = _parse_qualifier_top_n(request_form)
    if qualifier_top_n_result.is_err():
        return Err(qualifier_top_n_result.unwrap_err())

    return Ok(
        {
            'qualifier_source_stage_ids': [
                str(selected_source_stage_id)
                for selected_source_stage_id in selected_source_stage_ids
            ],
            'qualifier_top_n': qualifier_top_n_result.unwrap(),
            'qualifier_selection_mode': qualifier_selection_mode,
        }
    )


def _parse_selected_source_stage_ids(
    request_form, eligible_source_stages
) -> list[UUID]:
    selected_source_stage_ids: list[UUID] = []
    for raw_stage_id in request_form.getlist('qualifier_source_stage_ids'):
        try:
            selected_source_stage_id = UUID(raw_stage_id)
        except ValueError:
            continue
        if selected_source_stage_id not in eligible_source_stages:
            continue
        if selected_source_stage_id not in selected_source_stage_ids:
            selected_source_stage_ids.append(selected_source_stage_id)
    return selected_source_stage_ids


def _parse_qualifier_top_n(request_form) -> Result[int, str]:
    raw_top_n = (request_form.get('qualifier_top_n') or '1').strip()
    try:
        qualifier_top_n = int(raw_top_n)
    except ValueError:
        qualifier_top_n = 0
    if qualifier_top_n < 1 or qualifier_top_n > 128:
        return Err(gettext('Top N muss zwischen 1 und 128 liegen.'))
    return Ok(qualifier_top_n)


def build_current_manual_seed_values_by_participant_id(
    participants,
) -> dict[ParticipantID, int]:
    participant_count = len(participants)
    expected_seed = 1
    seen_seeds: set[int] = set()
    manual_seed_values_by_participant_id: dict[ParticipantID, int] = {}

    for participant in sorted(participants, key=_get_manual_seed_sort_key):
        seed = participant.seed
        if not _is_expected_manual_seed(
            seed, participant_count, seen_seeds, expected_seed
        ):
            continue

        manual_seed_values_by_participant_id[participant.id] = seed
        seen_seeds.add(seed)
        expected_seed += 1

    return manual_seed_values_by_participant_id


def _get_manual_seed_sort_key(participant) -> tuple:
    return (
        participant.seed if participant.seed is not None else 999_999,
        participant.name.lower(),
        str(participant.id),
    )


def _is_expected_manual_seed(
    seed: int | None,
    participant_count: int,
    seen_seeds: set[int],
    expected_seed: int,
) -> bool:
    return not (
        seed is None
        or seed < 1
        or seed > participant_count
        or seed in seen_seeds
        or seed != expected_seed
    )


def parse_stage_generation_auto_seed_participant_ids(
    request_form, allowed_participant_ids: set[ParticipantID]
) -> Result[list[ParticipantID], str]:
    auto_seed_participant_ids: list[ParticipantID] = []
    seen_participant_ids: set[ParticipantID] = set()

    for raw_participant_id in request_form.getlist('auto_seed_participant_ids'):
        try:
            participant_id = ParticipantID(UUID(raw_participant_id))
        except ValueError:
            return Err(
                gettext('Ungültige Zuordnung der automatischen Setzplätze.')
            )
        if participant_id not in allowed_participant_ids:
            return Err(gettext('Die Teilnehmerliste hat sich geändert.'))
        if participant_id in seen_participant_ids:
            return Err(
                gettext('Die Liste der automatischen Setzplätze ist ungültig.')
            )
        seen_participant_ids.add(participant_id)
        auto_seed_participant_ids.append(participant_id)

    if seen_participant_ids != allowed_participant_ids:
        return Err(
            gettext(
                'Die Teilnehmerliste hat sich geändert. Bitte die Setzlisten-Seite neu laden.'
            )
        )

    return Ok(auto_seed_participant_ids)


def parse_stage_generation_manual_seed_values_by_participant_id(
    request_form, allowed_participant_ids: set[ParticipantID]
) -> Result[dict[ParticipantID, int], str]:
    manual_seed_values_by_participant_id: dict[ParticipantID, int] = {}

    for raw_key, raw_value in request_form.items():
        if not raw_key.startswith('manual_seed_'):
            continue

        participant_id_result = _parse_manual_seed_participant_id(
            raw_key, allowed_participant_ids
        )
        if participant_id_result.is_err():
            return Err(participant_id_result.unwrap_err())

        seed_result = _parse_manual_seed_value(raw_value)
        if seed_result.is_err():
            return Err(seed_result.unwrap_err())

        seed = seed_result.unwrap()
        if seed is None:
            continue

        manual_seed_values_by_participant_id[participant_id_result.unwrap()] = (
            seed
        )

    return Ok(manual_seed_values_by_participant_id)


def _parse_manual_seed_participant_id(
    raw_key: str, allowed_participant_ids: set[ParticipantID]
) -> Result[ParticipantID, str]:
    try:
        participant_id = ParticipantID(
            UUID(raw_key.removeprefix('manual_seed_'))
        )
    except ValueError:
        return Err(gettext('Ungültige Eingabe des Setzplatzes.'))

    if participant_id not in allowed_participant_ids:
        return Err(gettext('Die Teilnehmerliste hat sich geändert.'))

    return Ok(participant_id)


def _parse_manual_seed_value(raw_value: str | None) -> Result[int | None, str]:
    normalized_raw_value = (raw_value or '').strip()
    if not normalized_raw_value:
        return Ok(None)

    try:
        seed = int(normalized_raw_value)
    except ValueError:
        return Err(gettext('Manuelle Setzplätze müssen Zahlen sein.'))

    if seed < 1:
        return Err(gettext('Manuelle Setzplätze müssen bei 1 beginnen.'))

    return Ok(seed)


def build_stage_generation_seed_rows(
    participants,
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_values_by_participant_id: dict[ParticipantID, int],
):
    participants_by_id = {
        participant.id: participant for participant in participants
    }
    auto_seed_by_participant_id = {
        participant_id: index
        for index, participant_id in enumerate(
            auto_seed_participant_ids, start=1
        )
    }
    final_seed_by_participant_id = _build_final_seed_by_participant_id(
        auto_seed_participant_ids, manual_seed_values_by_participant_id
    )

    rows = []
    for participant_id in auto_seed_participant_ids:
        manual_seed = manual_seed_values_by_participant_id.get(participant_id)
        rows.append(
            {
                'participant': participants_by_id[participant_id],
                'auto_seed': auto_seed_by_participant_id[participant_id],
                'manual_seed': manual_seed,
                'final_seed': final_seed_by_participant_id[participant_id],
                'is_manual': manual_seed is not None,
            }
        )

    return rows


def _build_final_seed_by_participant_id(
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_values_by_participant_id: dict[ParticipantID, int],
) -> dict[ParticipantID, int]:
    manual_prefix_participant_ids = [
        participant_id
        for participant_id, _seed in sorted(
            manual_seed_values_by_participant_id.items(),
            key=lambda item: item[1],
        )
    ]
    remaining_participant_ids = [
        participant_id
        for participant_id in auto_seed_participant_ids
        if participant_id not in manual_seed_values_by_participant_id
    ]
    return {
        participant_id: index
        for index, participant_id in enumerate(
            manual_prefix_participant_ids + remaining_participant_ids, start=1
        )
    }


def _is_stage_builder_v1_stage(stage: Stage) -> bool:
    return (stage.settings or {}).get('builder_kind') == 'stage_builder_v1'


def is_builder_round_robin_summary_stage(stage: Stage) -> bool:
    settings = stage.settings or {}
    return (
        _is_stage_builder_v1_stage(stage)
        and settings.get('builder_role') == 'preliminary'
        and stage.type == StageType.round_robin_groups
    )


def _is_builder_container_stage(stage: Stage) -> bool:
    return _is_stage_builder_v1_stage(stage) and bool(
        get_builder_container_child_stage_ids(stage)
    )


def _is_builder_preliminary_group_stage(stage: Stage) -> bool:
    settings = stage.settings or {}
    return (
        _is_stage_builder_v1_stage(stage)
        and settings.get('builder_role') == 'preliminary_group'
    )


def is_builder_main_stage_with_preliminary_source(stage: Stage) -> bool:
    settings = stage.settings or {}
    return (
        _is_stage_builder_v1_stage(stage)
        and settings.get('builder_role') == 'main'
        and bool(settings.get('builder_preliminary_stage_id'))
    )


def get_stage_generation_block_reason(
    stage: Stage,
    stages_by_id: dict[StageID, Stage],
    matches_by_stage: dict[StageID, list[Match]],
) -> str | None:
    guard_error = check_generation_allowed_for_stage(stage)
    if guard_error is not None:  # results would be deleted, or tournament over
        return guard_error
    if is_builder_preliminary_skipped(stage):
        return None  # everybody fits, the main stage starts directly
    settings = stage.settings or {}
    if settings.get('participant_source_mode') not in {
        'stage_qualifiers',
        'stage_match_qualifiers',
    }:
        return None

    return _get_qualifier_sources_block_reason(
        settings, stages_by_id, matches_by_stage
    )


def _get_qualifier_sources_block_reason(
    settings: dict,
    stages_by_id: dict[StageID, Stage],
    matches_by_stage: dict[StageID, list[Match]],
) -> str | None:
    source_stage_ids = parse_source_stage_ids(
        settings.get('qualifier_source_stage_ids', [])
    )
    if not source_stage_ids:
        return gettext(
            'Qualifikationsphasen fehlen. Konfiguriere zuerst die Vorrunden-Quelle.'
        )

    for source_stage_id in source_stage_ids:
        block_reason = _get_qualifier_source_block_reason(
            source_stage_id, stages_by_id, matches_by_stage
        )
        if block_reason is not None:
            return block_reason

    return None


def _get_qualifier_source_block_reason(
    source_stage_id: StageID,
    stages_by_id: dict[StageID, Stage],
    matches_by_stage: dict[StageID, list[Match]],
) -> str | None:
    source_stage = stages_by_id.get(source_stage_id)
    source_matches = matches_by_stage.get(source_stage_id, [])
    source_stage_name = (
        source_stage.name if source_stage is not None else gettext('Quelle')
    )

    if not source_matches:
        return gettext(
            'Phase "%(stage_name)s" hat noch keine generierten Matches.',
            stage_name=source_stage_name,
        )

    if any(match.state != MatchState.completed for match in source_matches):
        return gettext(
            'Phase "%(stage_name)s" ist noch nicht abgeschlossen.',
            stage_name=source_stage_name,
        )

    return None


def build_stage_display_rows(stages: list[Stage]) -> list[dict]:
    rows = []
    consumed_stage_ids: set = set()
    stages_by_id = {str(stage.id): stage for stage in stages}

    for stage in sorted(stages, key=lambda item: item.order_no):
        if stage.id in consumed_stage_ids:
            continue

        if _is_builder_container_stage(stage):
            row = _build_container_display_row(stage, stages_by_id)
            consumed_stage_ids.update(
                child_stage.id for child_stage in row['child_stages']
            )
            rows.append(row)
            continue

        rows.append({'kind': 'stage', 'stage': stage})

    return rows


def _build_container_display_row(
    stage: Stage, stages_by_id: dict[str, Stage]
) -> dict:
    child_stages = [
        stages_by_id[str(stage_id)]
        for stage_id in get_builder_container_child_stage_ids(stage)
        if str(stage_id) in stages_by_id
    ]
    return {
        'kind': 'builder_container',
        'stage': stage,
        'child_stages': child_stages,
    }


def build_visible_stage_tabs(stages: list[Stage]) -> list[Stage]:
    return [stage for stage in stages if not _is_builder_container_stage(stage)]


def build_stage_builder_meta(stage: Stage) -> dict | None:
    if not _is_stage_builder_v1_stage(stage):
        return None

    settings = stage.settings or {}
    role = settings.get('builder_role')
    main_stage_size = settings.get('builder_main_stage_size')
    generation_basis = settings.get('builder_generation_basis') or 'ready'
    lines = [
        gettext(
            'Teilnehmerbasis: %(basis)s',
            basis=(
                gettext('Bereit')
                if generation_basis == 'ready'
                else generation_basis
            ),
        )
    ]

    role_label, role_lines = build_stage_builder_role_meta(
        stage, settings, role
    )
    lines.extend(role_lines)

    if main_stage_size:
        lines.append(
            gettext('Größe des Hauptturniers: %(size)s', size=main_stage_size)
        )

    return {
        'role_label': role_label,
        'lines': lines,
    }


def build_stage_builder_generation_summary(
    stage: Stage,
    resolved_stage: Stage,
    participant_count: int,
    match_count: int | None = None,
) -> dict | None:
    if not _is_stage_builder_v1_stage(stage):
        return None

    settings = resolved_stage.settings or {}
    role = (stage.settings or {}).get('builder_role')
    main_stage_size = settings.get('builder_main_stage_size')
    lines = [
        gettext(
            'Aktuelle Generierungsbasis: %(count)s bereite Teilnehmer',
            count=participant_count,
        )
    ]

    if role == 'preliminary':
        lines.extend(
            build_preliminary_generation_summary_lines(
                stage, settings, participant_count, match_count
            )
        )
    else:
        lines.append(
            get_main_generation_summary_line(
                stage, participant_count, main_stage_size
            )
        )

    return {
        'title': gettext('Turnierplaner'),
        'lines': lines,
    }


def build_round_robin_generation_intro(
    stage: Stage,
    resolved_stage: Stage,
    participant_count: int,
) -> dict | None:
    if not is_builder_round_robin_summary_stage(stage):
        return None

    settings = resolved_stage.settings or {}
    main_stage_size = settings.get('builder_main_stage_size')
    group_count = settings.get('group_count')
    qualifiers_per_group = settings.get('builder_resolved_qualifiers_per_group')
    round_robin_builder_mode = get_round_robin_builder_mode(stage, settings)

    group_sizes: list[int] = []
    if group_count:
        group_sizes = distribute_evenly(participant_count, int(group_count))

    return {
        'is_manual_mode': round_robin_builder_mode == 'manual_group_count',
        'distribution_summary': (
            format_group_distribution_summary(group_sizes)
            if group_sizes
            else None
        ),
        'qualification_summary': _build_round_robin_qualification_summary(
            qualifiers_per_group, main_stage_size
        ),
    }


def _build_round_robin_qualification_summary(
    qualifiers_per_group, main_stage_size
) -> str | None:
    if not (qualifiers_per_group and main_stage_size):
        return None

    return gettext(
        'Top %(top_n)s pro Gruppe -> %(size)s für das Hauptturnier',
        top_n=qualifiers_per_group,
        size=main_stage_size,
    )


def build_stage_builder_container_preview_meta(
    party_id: PartyID, tournament_id: TournamentID, stage: Stage
) -> dict | None:
    if not is_builder_round_robin_summary_stage(stage):
        return None

    preview_result = preview_stage_match_generation(
        party_id, tournament_id, stage.id
    )
    if preview_result.is_err():
        return None

    preview = preview_result.unwrap()
    intro = build_round_robin_generation_intro(
        stage,
        preview.stage,
        preview.participant_count,
    )
    if intro is None:
        return None

    return {
        'participant_count': preview.participant_count,
        'distribution_summary': intro.get('distribution_summary'),
        'qualification_summary': intro.get('qualification_summary'),
    }


def build_stage_builder_main_form(
    *,
    tournament,
    state: dict,
    erroneous_form: StageBuilderMainForm | None = None,
) -> StageBuilderMainForm:
    if erroneous_form is not None:
        return erroneous_form

    return StageBuilderMainForm(
        tournament_mode=tournament.mode,
        data={
            'generation_basis': state.get('generation_basis') or 'ready',
            'main_stage_type': state.get('main_stage_type')
            or (
                StageType.ffa_single_elimination.value
                if is_ffa_stage_builder_tournament(tournament)
                else StageType.double_elimination.value
            ),
            'main_stage_size': state.get('main_stage_size')
            or get_stage_builder_default_main_stage_size(tournament),
            'max_players_per_match': state.get('max_players_per_match') or 8,
        },
    )


def build_stage_builder_preliminary_form(
    *,
    tournament,
    state: dict,
    erroneous_form: StageBuilderPreliminaryForm | None = None,
) -> StageBuilderPreliminaryForm:
    if erroneous_form is not None:
        return erroneous_form

    main_stage_type = _parse_state_main_stage_type(state)

    return StageBuilderPreliminaryForm(
        tournament_mode=tournament.mode,
        main_stage_type=main_stage_type,
        data={
            'use_preliminary': state.get('use_preliminary', True),
            'preliminary_type': state.get('preliminary_type')
            or _get_default_preliminary_type(tournament, main_stage_type),
            'round_robin_builder_mode': (
                state.get('round_robin_builder_mode') or 'standard'
            ),
            'round_robin_group_count': state.get('round_robin_group_count'),
            'swiss_threshold': state.get('swiss_threshold') or 3,
        },
    )


def _parse_state_main_stage_type(state: dict) -> StageType | None:
    raw_main_stage_type = state.get('main_stage_type')
    if not raw_main_stage_type:
        return None

    try:
        return StageType(raw_main_stage_type)
    except ValueError:
        return None


def _get_default_preliminary_type(
    tournament, main_stage_type: StageType | None
) -> str:
    if main_stage_type == StageType.ffa_flatout2_single_elimination:
        return StageType.ffa_flatout2_single_elimination.value

    return (
        StageType.ffa_single_elimination.value
        if is_ffa_stage_builder_tournament(tournament)
        else StageType.round_robin_groups.value
    )


def build_stage_builder_timing_form(
    *, state: dict, erroneous_form: StageBuilderTimingForm | None = None
) -> StageBuilderTimingForm:
    if erroneous_form is not None:
        return erroneous_form

    return StageBuilderTimingForm(
        data={
            'match_duration_minutes': state.get('match_duration_minutes'),
            'max_matches_per_round': state.get('max_matches_per_round'),
            'break_between_rounds_minutes': state.get(
                'break_between_rounds_minutes', 0
            ),
        }
    )


def stage_builder_steps() -> list[dict[str, str]]:
    return [
        {'id': 'main', 'number': '1', 'label': gettext('Hauptturnier')},
        {'id': 'preliminary', 'number': '2', 'label': gettext('Vorrunde')},
        {'id': 'timing', 'number': '3', 'label': gettext('Zeitplan')},
        {'id': 'review', 'number': '4', 'label': gettext('Prüfen')},
    ]


def assert_tournament_has_no_stages_for_builder_or_redirect(
    party: Party, tournament
):
    stages = get_stages_for_tournament(party.id, tournament.id)
    if stages:
        flash_error(
            gettext(
                'Der Turnierplaner arbeitet nur auf Turnieren ohne vorhandene Phasen.'
            )
        )
        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='stages',
        )

    return None


def build_stage_builder_review_preview(
    party: Party, tournament, *, state: dict
) -> dict | None:
    if not is_stage_builder_main_complete(state):
        return None

    plan_arguments = parse_review_plan_arguments(state)
    if plan_arguments is None:
        return None

    main_stage_type, main_stage_size, preliminary_type = plan_arguments

    preview_result = preview_stage_builder_plan(
        party.id,
        tournament.id,
        generation_basis=str(state.get('generation_basis') or ''),
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        max_players_per_match=state.get('max_players_per_match'),
        preliminary_type=preliminary_type,
        round_robin_builder_mode=state.get('round_robin_builder_mode'),
        round_robin_group_count=state.get('round_robin_group_count'),
        swiss_threshold=state.get('swiss_threshold'),
    )
    if preview_result.is_err():
        return {
            'title': gettext('Aktuelle Vorschau des Turnierplaners'),
            'error': preview_result.unwrap_err(),
        }

    preview = preview_result.unwrap()
    lines = build_review_preview_lines(
        preview, main_stage_type, main_stage_size, preliminary_type
    )

    return {
        'title': gettext('Aktuelle Vorschau des Turnierplaners'),
        'lines': lines,
    }


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
