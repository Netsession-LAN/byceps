"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

import re
from uuid import UUID

from flask_babel import gettext

from byceps.services.party.models import Party
from byceps.services.party.models import PartyID
from byceps.util.framework.flash import flash_error
from byceps.util.result import Err, Ok, Result
from byceps.util.views import redirect_to

from ...forms import (
    StageBuilderMainForm,
    StageBuilderPreliminaryForm,
    StageBuilderTimingForm,
    StageForm,
)
from ...flatout2 import (
    FLATOUT2_MAX_RACES_PER_ROUND,
    FLATOUT2_MODE_CHOICES,
    FLATOUT2_MODE_SPECS,
    FLATOUT2_TRACK_CHOICES_BY_MODE,
    FLATOUT2_TRACK_SET_BY_MODE,
    FLATOUT2_VEHICLE_CHOICES_BY_MODE,
    FLATOUT2_VEHICLE_SET_BY_MODE,
)
from ...models import (
    Match,
    MatchState,
    ParticipantID,
    Stage,
    StageID,
    StageType,
    TournamentID,
    TournamentMode,
)
from ...result_report_mode import RESULT_REPORT_MODE_ADMIN_ONLY
from ...stage_builder_preview import preview_stage_builder_plan
from ...stage_builder_settings import STAGE_BUILDER_MAIN_STAGE_SIZES
from ...stage_generation import preview_stage_match_generation
from ...swiss_thresholds import (
    get_configured_swiss_threshold,
    get_swiss_round_count_for_threshold,
    get_swiss_threshold_for_round_count,
)
from ...tournament_queries import get_stages_for_tournament
from ...score_parsing import get_ffa_points_per_kill
from ...engines.bracket_helpers import distribute_evenly
from ..site.builder_helpers import get_builder_container_child_stage_ids


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

    return '1024'


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
        except (TypeError, ValueError):
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
        except (TypeError, ValueError):
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


def _parse_ffa_placement_points_text(raw_text: str | None) -> Result[list[dict], str]:
    normalized_text = (raw_text or '').strip()
    if not normalized_text:
        return Err(
            gettext(
                'Bitte für dieses FFA-Format ein Platz-zu-Punkte-Schema angeben.'
            )
        )

    rules = []
    pattern = re.compile(
        r'^(?:platz\s*#?\s*)?(\d+)(?:\s*-\s*(\d+))?\s*(?:=|:|->)?\s*(\d+)\s*(?:punkte?|pts?)?$',
        re.IGNORECASE,
    )

    for line_no, raw_line in enumerate(normalized_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        match = pattern.fullmatch(line)
        if match is None:
            return Err(
                gettext(
                    'Ungültiges Platz-zu-Punkte-Schema in Zeile %(line_no)s.',
                    line_no=line_no,
                )
            )

        from_place = int(match.group(1))
        to_place = int(match.group(2) or match.group(1))
        points = int(match.group(3))

        if from_place < 1 or to_place < 1:
            return Err(
                gettext(
                    'Plätze müssen in Zeile %(line_no)s bei 1 oder höher liegen.',
                    line_no=line_no,
                )
            )
        if to_place < from_place:
            return Err(
                gettext(
                    'Der Platzbereich in Zeile %(line_no)s ist ungültig.',
                    line_no=line_no,
                )
            )
        if points < 0 or points > 999:
            return Err(
                gettext(
                    'Die Punkte in Zeile %(line_no)s müssen zwischen 0 und 999 liegen.',
                    line_no=line_no,
                )
            )

        rules.append(
            {
                'from_place': from_place,
                'to_place': to_place,
                'points': points,
            }
        )

    if not rules:
        return Err(
            gettext(
                'Bitte für dieses FFA-Format mindestens eine Platz-zu-Punkte-Regel angeben.'
            )
        )

    rules.sort(key=lambda item: (item['from_place'], item['to_place']))

    previous_to_place = 0
    for rule in rules:
        if rule['from_place'] <= previous_to_place:
            return Err(
                gettext(
                    'Platzbereiche im FFA-Schema dürfen sich nicht überlappen.'
                )
            )
        previous_to_place = rule['to_place']

    return Ok(rules)


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
        candidates = [max_players_per_match]
        if isinstance(existing_settings, dict):
            candidates.append(existing_settings.get('max_players_per_match'))

        for candidate in candidates:
            try:
                parsed = int(candidate)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed

    participant_limit = getattr(tournament, 'participant_limit', None)
    if (
        stage_type
        != StageType.ffa_single_elimination
        and isinstance(participant_limit, int)
        and participant_limit > 0
    ):
        return participant_limit

    parsed_rules_result = _parse_ffa_placement_points_text(placement_points_text)
    if parsed_rules_result.is_err():
        return 0

    rules = parsed_rules_result.unwrap()
    if not rules:
        return 0

    return max(int(rule['to_place']) for rule in rules)


def stage_settings_from_form(
    form: StageForm, *, existing_settings: dict | None = None
) -> Result[dict, str]:
    try:
        stage_type = StageType(form.type.data)
    except ValueError:
        stage_type = None

    settings = {}
    if stage_type == StageType.swiss and form.swiss_threshold.data is None:
        return Err(gettext('Bitte eine Swiss-Schwelle auswählen.'))

    if form.round_count.data and stage_type != StageType.swiss:
        settings['round_count'] = form.round_count.data
    if stage_type == StageType.swiss and form.swiss_threshold.data:
        settings['swiss_threshold'] = form.swiss_threshold.data
        settings['round_count'] = get_swiss_round_count_for_threshold(
            form.swiss_threshold.data
        )
    if form.max_players_per_match.data and stage_type != StageType.ffa_simple:
        settings['max_players_per_match'] = form.max_players_per_match.data
    if form.group_size.data:
        settings['group_size'] = form.group_size.data
    if _is_ffa_scoring_stage_type(stage_type):
        parsed_rules_result = _parse_ffa_placement_points_text(
            form.placement_points.data
        )
        if parsed_rules_result.is_err():
            return Err(parsed_rules_result.unwrap_err())

        settings['placement_points_rules'] = parsed_rules_result.unwrap()
        settings['points_per_kill'] = (
            form.points_per_kill.data
            if form.points_per_kill.data is not None
            else 1
        )
    if form.match_duration_minutes.data:
        settings['match_duration_minutes'] = form.match_duration_minutes.data
    if (
        form.max_matches_per_round.data
        and stage_type
        not in {
            StageType.ffa_simple,
            StageType.ffa_single_elimination,
            StageType.ffa_flatout2_single_elimination,
        }
    ):
        settings['max_matches_per_round'] = form.max_matches_per_round.data
    if form.break_between_rounds_minutes.data is not None:
        settings['break_between_rounds_minutes'] = (
            form.break_between_rounds_minutes.data
        )
    settings['result_report_mode'] = (
        RESULT_REPORT_MODE_ADMIN_ONLY
        if is_ffa_result_stage_type(stage_type)
        else (form.result_report_mode.data or 'both_must_confirm')
    )

    if existing_settings is not None:
        for key in (
            'participant_source_mode',
            'qualifier_source_stage_ids',
            'qualifier_top_n',
        ):
            if key in existing_settings:
                settings[key] = existing_settings[key]

    return Ok(settings)


def participant_source_settings_from_form(
    request_form, *, eligible_source_stages
):
    mode = (request_form.get('participant_source_mode') or 'tournament').strip()
    if mode not in {'tournament', 'stage_qualifiers'}:
        return Err(gettext('Ungültige Teilnehmerquelle.'))

    settings = {'participant_source_mode': mode}

    if mode != 'stage_qualifiers':
        return Ok(settings)

    qualifier_selection_mode = (
        request_form.get('qualifier_selection_mode') or 'per_stage'
    ).strip()
    if qualifier_selection_mode not in {'per_stage', 'per_group'}:
        return Err(gettext('Ungültiger Qualifikationsmodus.'))

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

    if not selected_source_stage_ids:
        return Err(
            gettext('Bitte mindestens eine vorherige Stage als Quelle auswählen.')
        )

    raw_top_n = (request_form.get('qualifier_top_n') or '1').strip()
    try:
        qualifier_top_n = int(raw_top_n)
    except ValueError:
        qualifier_top_n = 0
    if qualifier_top_n < 1 or qualifier_top_n > 128:
        return Err(gettext('Top N muss zwischen 1 und 128 liegen.'))

    settings['qualifier_source_stage_ids'] = [
        str(selected_source_stage_id)
        for selected_source_stage_id in selected_source_stage_ids
    ]
    settings['qualifier_top_n'] = qualifier_top_n
    settings['qualifier_selection_mode'] = qualifier_selection_mode
    return Ok(settings)


def build_current_manual_seed_values_by_participant_id(
    participants,
) -> dict[ParticipantID, int]:
    participant_count = len(participants)
    expected_seed = 1
    seen_seeds: set[int] = set()
    manual_seed_values_by_participant_id: dict[ParticipantID, int] = {}

    for participant in sorted(
        participants,
        key=lambda item: (
            item.seed if item.seed is not None else 999_999,
            item.name.lower(),
            str(item.id),
        ),
    ):
        seed = participant.seed
        if (
            seed is None
            or seed < 1
            or seed > participant_count
            or seed in seen_seeds
            or seed != expected_seed
        ):
            continue

        manual_seed_values_by_participant_id[participant.id] = seed
        seen_seeds.add(seed)
        expected_seed += 1

    return manual_seed_values_by_participant_id


def parse_stage_generation_auto_seed_participant_ids(
    request_form, allowed_participant_ids: set[ParticipantID]
) -> Result[list[ParticipantID], str]:
    auto_seed_participant_ids: list[ParticipantID] = []
    seen_participant_ids: set[ParticipantID] = set()

    for raw_participant_id in request_form.getlist('auto_seed_participant_ids'):
        try:
            participant_id = ParticipantID(UUID(raw_participant_id))
        except ValueError:
            return Err(gettext('Ungültige Auto-Seed-Zuordnung.'))
        if participant_id not in allowed_participant_ids:
            return Err(gettext('Die Teilnehmerliste hat sich geändert.'))
        if participant_id in seen_participant_ids:
            return Err(gettext('Die Auto-Seed-Liste ist ungültig.'))
        seen_participant_ids.add(participant_id)
        auto_seed_participant_ids.append(participant_id)

    if seen_participant_ids != allowed_participant_ids:
        return Err(
            gettext(
                'Die Teilnehmerliste hat sich geändert. Bitte die Seeding-Seite neu laden.'
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

        try:
            participant_id = ParticipantID(
                UUID(raw_key.removeprefix('manual_seed_'))
            )
        except ValueError:
            return Err(gettext('Ungültige Seed-Eingabe.'))

        if participant_id not in allowed_participant_ids:
            return Err(gettext('Die Teilnehmerliste hat sich geändert.'))

        normalized_raw_value = (raw_value or '').strip()
        if not normalized_raw_value:
            continue

        try:
            seed = int(normalized_raw_value)
        except ValueError:
            return Err(gettext('Manuelle Seeds müssen Zahlen sein.'))

        if seed < 1:
            return Err(gettext('Manuelle Seeds müssen bei 1 beginnen.'))

        manual_seed_values_by_participant_id[participant_id] = seed

    return Ok(manual_seed_values_by_participant_id)


def build_stage_generation_seed_rows(
    participants,
    auto_seed_participant_ids: list[ParticipantID],
    manual_seed_values_by_participant_id: dict[ParticipantID, int],
):
    participants_by_id = {participant.id: participant for participant in participants}
    auto_seed_by_participant_id = {
        participant_id: index
        for index, participant_id in enumerate(auto_seed_participant_ids, start=1)
    }
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
    final_seed_by_participant_id = {
        participant_id: index
        for index, participant_id in enumerate(
            manual_prefix_participant_ids + remaining_participant_ids, start=1
        )
    }

    rows = []
    for participant_id in auto_seed_participant_ids:
        participant = participants_by_id[participant_id]
        manual_seed = manual_seed_values_by_participant_id.get(participant_id)
        rows.append(
            {
                'participant': participant,
                'auto_seed': auto_seed_by_participant_id[participant_id],
                'manual_seed': manual_seed,
                'final_seed': final_seed_by_participant_id[participant_id],
                'is_manual': manual_seed is not None,
            }
        )

    return rows


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
    settings = stage.settings or {}
    if settings.get('participant_source_mode') not in {
        'stage_qualifiers',
        'stage_match_qualifiers',
    }:
        return None

    source_stage_ids = []
    for raw_stage_id in settings.get('qualifier_source_stage_ids', []):
        try:
            source_stage_ids.append(StageID(UUID(str(raw_stage_id))))
        except ValueError:
            continue

    if not source_stage_ids:
        return gettext(
            'Qualifikations-Stages fehlen. Konfiguriere zuerst die Vorrunden-Quelle.'
        )

    for source_stage_id in source_stage_ids:
        source_stage = stages_by_id.get(source_stage_id)
        source_matches = matches_by_stage.get(source_stage_id, [])
        source_stage_name = (
            source_stage.name if source_stage is not None else gettext('Quelle')
        )

        if not source_matches:
            return gettext(
                'Stage "%(stage_name)s" hat noch keine generierten Matches.',
                stage_name=source_stage_name,
            )

        if any(match.state != MatchState.completed for match in source_matches):
            return gettext(
                'Stage "%(stage_name)s" ist noch nicht abgeschlossen.',
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
            child_stages = [
                stages_by_id[str(stage_id)]
                for stage_id in get_builder_container_child_stage_ids(stage)
                if str(stage_id) in stages_by_id
            ]
            consumed_stage_ids.update(child_stage.id for child_stage in child_stages)
            rows.append(
                {
                    'kind': 'builder_container',
                    'stage': stage,
                    'child_stages': child_stages,
                }
            )
            continue

        rows.append({'kind': 'stage', 'stage': stage})

    return rows


def build_visible_stage_tabs(stages: list[Stage]) -> list[Stage]:
    return [
        stage
        for stage in stages
        if not _is_builder_container_stage(stage)
    ]


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
                gettext('Ready')
                if generation_basis == 'ready'
                else generation_basis
            ),
        )
    ]

    if role == 'preliminary':
        role_label = (
            gettext('Builder V1: Vorrunden-Übersicht')
            if stage.type == StageType.round_robin_groups
            else gettext('Builder V1: Vorrunde')
        )
        if stage.type == StageType.round_robin_groups:
            lines.append(
                gettext(
                    'Diese Stage ist die reine Summary der Gruppenphase. Eigene Matches liegen in den Gruppen-Stages.'
                )
            )
            lines.append(
                gettext(
                    'Round Robin Groups werden bei der Generierung gleichmäßig verteilt.'
                )
            )
            lines.append(gettext('Qualifikation: gleich viele pro Gruppe'))
            if settings.get('builder_materialized_group_stage_ids'):
                lines.append(
                    gettext(
                        'Diese Übersicht wurde bereits in echte Gruppen-Stages materialisiert.'
                    )
                )
        elif stage.type == StageType.swiss:
            lines.append(
                gettext(
                    'Swiss qualifiziert in V1 als Gesamtranking ins Hauptturnier.'
                )
            )
        elif settings.get('builder_materialized_stage_ids'):
            lines.append(
                gettext(
                    'Diese Vorrunden-Übersicht enthält eigene Runden-Stages, die nacheinander vorbereitet werden.'
                )
            )
    elif role == 'preliminary_round':
        role_label = (
            gettext('Builder V1')
            if stage.type == StageType.ffa_flatout2_single_elimination
            else gettext(
                'Builder V1: Vorrunde %(title)s',
                title=settings.get('builder_display_title') or '?',
            )
        )
        lines.append(
            gettext('Teilnehmerquelle: Builder-Qualifikanten der Vorrunde')
        )
    elif role == 'main_round':
        role_label = (
            gettext('Builder V1')
            if stage.type == StageType.ffa_flatout2_single_elimination
            else gettext(
                'Builder V1: Hauptturnier %(title)s',
                title=settings.get('builder_display_title') or '?',
            )
        )
        lines.append(
            gettext('Teilnehmerquelle: Builder-Qualifikanten der Vorstufe')
        )
    elif role == 'preliminary_group':
        role_label = gettext(
            'Builder V1: Vorrunden-Gruppe %(label)s',
            label=settings.get('builder_group_label') or '?',
        )
        lines.append(gettext('Teilnehmerquelle: feste Builder-Gruppenzuweisung'))
        qualifier_top_n = settings.get('builder_group_qualifier_top_n')
        if qualifier_top_n:
            lines.append(
                gettext(
                    'Qualifikation: Top %(top_n)s ins Hauptturnier',
                    top_n=qualifier_top_n,
                )
            )
    else:
        role_label = (
            gettext('Builder V1')
            if stage.type == StageType.ffa_flatout2_single_elimination
            else gettext('Builder V1: Hauptturnier')
        )
        if settings.get('builder_preliminary_stage_id'):
            lines.append(gettext('Teilnehmerquelle: automatische Qualifikation'))
        else:
            lines.append(
                gettext('Teilnehmerquelle: direkte Ready-Teilnehmer')
            )

    if main_stage_size:
        lines.append(
            gettext('Main Stage Größe: %(size)s', size=main_stage_size)
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
    lines = [gettext('Aktuelle Generierungsbasis: %(count)s ready Teilnehmer', count=participant_count)]

    if role == 'preliminary':
        if stage.type == StageType.round_robin_groups:
            round_robin_builder_mode = settings.get(
                'builder_round_robin_mode'
            ) or (stage.settings or {}).get('builder_round_robin_mode')
            group_count = settings.get('group_count')
            qualifiers_per_group = settings.get(
                'builder_resolved_qualifiers_per_group'
            )
            min_group_size = settings.get('builder_resolved_group_size_min')
            max_group_size = settings.get('builder_resolved_group_size_max')
            if round_robin_builder_mode == 'manual_group_count':
                lines.append(
                    gettext(
                        'Strategie: Expertenoption mit manueller Gruppenzahl'
                    )
                )
                if group_count:
                    lines.append(
                        gettext(
                            'Manuell vorgegeben: %(count)s Gruppen',
                            count=group_count,
                        )
                    )
            else:
                lines.append(
                    gettext(
                        'Strategie: Empfohlener Standard, bevorzugt 8 Gruppen / Top 2 bei Main Stage 16'
                    )
                )
            if group_count:
                lines.append(
                    gettext('Gruppen: %(count)s', count=group_count)
                )
            if min_group_size and max_group_size:
                if min_group_size == max_group_size:
                    lines.append(
                        gettext(
                            'Gruppengröße: %(size)s Teilnehmer',
                            size=min_group_size,
                        )
                    )
                else:
                    lines.append(
                        gettext(
                            'Gruppengrößen: %(min)s bis %(max)s Teilnehmer',
                            min=min_group_size,
                            max=max_group_size,
                        )
                    )
            if qualifiers_per_group and main_stage_size:
                lines.append(
                    gettext(
                        'Qualifikation: Top %(top_n)s pro Gruppe -> %(size)s für das Hauptturnier',
                        top_n=qualifiers_per_group,
                        size=main_stage_size,
                    )
                )
            if group_count:
                group_sizes = distribute_evenly(participant_count, int(group_count))
                lines.append(_format_group_distribution_summary(group_sizes))
                round_summary = _format_round_robin_global_round_summary(
                    group_sizes
                )
                if round_summary is not None:
                    lines.append(round_summary)
            if match_count is not None:
                lines.append(
                    gettext(
                        '%(count)s Vorrunden-Matches insgesamt',
                        count=match_count,
                    )
                )
            lines.append(
                gettext(
                    'Beim Erzeugen werden daraus echte Gruppen-Stages wie "Vorrunde Gruppe A", "Vorrunde Gruppe B" usw.'
                )
            )
            lines.append(
                gettext(
                    'Die Rundentabelle darunter zeigt globale Runden über alle Gruppen. Runde 1 bedeutet die erste Spielrunde in jeder Gruppe.'
                )
            )
            lines.append(
                gettext(
                    'Round Count und Group Size werden bei Builder-Vorrunden aus den aktuellen ready Teilnehmern abgeleitet und sind deshalb nicht als feste statische Stage-Werte hinterlegt.'
                )
            )
        elif stage.type == StageType.swiss and main_stage_size:
            lines.append(
                gettext(
                    'Qualifikation: Top %(size)s insgesamt aus Swiss ins Hauptturnier',
                    size=main_stage_size,
                )
            )
    else:
        if (stage.settings or {}).get('builder_preliminary_stage_id'):
            if participant_count <= int(main_stage_size or 0):
                lines.append(
                    gettext(
                        'Die Vorrunde ist aktuell nicht nötig. Das Hauptturnier wird direkt aus den ready Teilnehmern erzeugt.'
                    )
                )
            else:
                lines.append(
                    gettext(
                        'Das Hauptturnier wird aus den Qualifikanten der Vorrunde gespeist.'
                    )
                )
        else:
            lines.append(
                gettext('Diese Main Stage wird direkt aus ready Teilnehmern erzeugt.')
            )

    return {
        'title': gettext('Builder-Logik'),
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
    qualifiers_per_group = settings.get(
        'builder_resolved_qualifiers_per_group'
    )
    round_robin_builder_mode = settings.get(
        'builder_round_robin_mode'
    ) or (stage.settings or {}).get('builder_round_robin_mode')

    group_sizes: list[int] = []
    if group_count:
        group_sizes = distribute_evenly(participant_count, int(group_count))

    return {
        'is_manual_mode': round_robin_builder_mode == 'manual_group_count',
        'distribution_summary': (
            _format_group_distribution_summary(group_sizes)
            if group_sizes
            else None
        ),
        'qualification_summary': (
            gettext(
                'Top %(top_n)s pro Gruppe -> %(size)s für das Hauptturnier',
                top_n=qualifiers_per_group,
                size=main_stage_size,
            )
            if qualifiers_per_group and main_stage_size
            else None
        ),
    }


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


def _format_group_distribution_summary(group_sizes: list[int]) -> str:
    if not group_sizes:
        return gettext('Keine Gruppenverteilung verfügbar.')

    counts_by_size: dict[int, int] = {}
    for size in group_sizes:
        counts_by_size[size] = counts_by_size.get(size, 0) + 1

    parts = [
        gettext('%(count)s Gruppen ? %(size)s', count=count, size=size)
        for size, count in sorted(counts_by_size.items(), reverse=True)
    ]
    return gettext('Konkrete Verteilung: %(parts)s', parts=', '.join(parts))


def _format_round_robin_global_round_summary(group_sizes: list[int]) -> str | None:
    if not group_sizes:
        return None

    matches_by_round: list[int] = []
    for group_size in group_sizes:
        round_count = group_size if group_size % 2 == 1 else max(1, group_size - 1)
        matches_per_round = group_size // 2
        for round_index in range(round_count):
            if round_index >= len(matches_by_round):
                matches_by_round.append(0)
            matches_by_round[round_index] += matches_per_round

    if not matches_by_round:
        return None

    parts = [
        gettext(
            'Runde %(round_no)s: %(match_count)s Matches',
            round_no=round_index + 1,
            match_count=match_count,
        )
        for round_index, match_count in enumerate(matches_by_round)
    ]
    return gettext('Globale Rundensicht: %(parts)s', parts=', '.join(parts))


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
            'max_players_per_match': state.get('max_players_per_match')
            or 8,
        }
    )


def build_stage_builder_preliminary_form(
    *,
    tournament,
    state: dict,
    erroneous_form: StageBuilderPreliminaryForm | None = None,
) -> StageBuilderPreliminaryForm:
    if erroneous_form is not None:
        return erroneous_form

    main_stage_type = None
    raw_main_stage_type = state.get('main_stage_type')
    if raw_main_stage_type:
        try:
            main_stage_type = StageType(raw_main_stage_type)
        except ValueError:
            main_stage_type = None

    return StageBuilderPreliminaryForm(
        tournament_mode=tournament.mode,
        main_stage_type=main_stage_type,
        data={
            'use_preliminary': state.get('use_preliminary', True),
            'preliminary_type': state.get('preliminary_type')
            or (
                StageType.ffa_flatout2_single_elimination.value
                if main_stage_type == StageType.ffa_flatout2_single_elimination
                else (
                    StageType.ffa_single_elimination.value
                    if is_ffa_stage_builder_tournament(tournament)
                    else StageType.round_robin_groups.value
                )
            ),
            'round_robin_builder_mode': (
                state.get('round_robin_builder_mode') or 'standard'
            ),
            'round_robin_group_count': state.get('round_robin_group_count'),
            'swiss_threshold': state.get('swiss_threshold') or 3,
        }
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
        {'id': 'timing', 'number': '3', 'label': gettext('Timing')},
        {'id': 'review', 'number': '4', 'label': gettext('Prüfen')},
    ]


def assert_tournament_has_no_stages_for_builder_or_redirect(
    party: Party, tournament
):
    stages = get_stages_for_tournament(party.id, tournament.id)
    if stages:
        flash_error(
            gettext(
                'Der Stage Builder V1 arbeitet nur auf Turnieren ohne vorhandene Stages.'
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

    try:
        main_stage_type = StageType(state['main_stage_type'])
        main_stage_size = int(state['main_stage_size'])
    except (KeyError, TypeError, ValueError):
        return None

    preliminary_type = None
    if state.get('use_preliminary'):
        raw_preliminary_type = state.get('preliminary_type')
        if not raw_preliminary_type:
            return None
        try:
            preliminary_type = StageType(raw_preliminary_type)
        except ValueError:
            return None

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
            'title': gettext('Aktuelle Builder-Vorschau'),
            'error': preview_result.unwrap_err(),
        }

    preview = preview_result.unwrap()
    lines = [
        gettext(
            'Aktuelle Generierungsbasis: %(count)s ready Teilnehmer',
            count=preview['participant_count'],
        )
    ]

    if main_stage_type in {
        StageType.ffa_single_elimination,
        StageType.ffa_flatout2_single_elimination,
    }:
        if preview.get('generation_blocked_without_preliminary'):
            lines.append(
                gettext(
                    'Mit der aktuellen Ready-Zahl würde die Main Stage noch blockieren: %(participant_count)s Teilnehmer überschreiten die Zielgröße %(target_size)s.',
                    participant_count=preview.get('participant_count') or 0,
                    target_size=main_stage_size,
                )
            )
            lines.append(
                gettext(
                    'Aktiviere eine Vorrunde oder erhöhe die Main-Stage-Zielgröße.'
                )
            )
        elif preview.get('uses_preliminary'):
            lines.append(
                gettext(
                    'Vorrunde aktiv: %(participant_count)s Ready-Teilnehmer starten zuerst in %(preliminary_type)s.',
                    participant_count=preview.get('participant_count') or 0,
                    preliminary_type=(
                        'FlatOut 2'
                        if preview.get('preliminary_type')
                        == StageType.ffa_flatout2_single_elimination
                        else 'FFA Single Elimination'
                    ),
                )
            )
            lines.append(
                gettext(
                    'Danach ziehen exakt %(count)s Teilnehmer in die Main Stage ein.',
                    count=preview.get('main_stage_participant_count')
                    or main_stage_size,
                )
            )
        else:
            lines.append(
                gettext(
                    'Die Main Stage startet direkt mit %(count)s Ready-Teilnehmern.',
                    count=preview.get('main_stage_participant_count')
                    or preview.get('participant_count')
                    or 0,
                )
            )

        lines.append(
            gettext(
                'Heat-Größe: bis zu %(count)s Teilnehmer pro Match.',
                count=preview.get('max_players_per_match') or '-',
            )
        )
        if main_stage_type == StageType.ffa_flatout2_single_elimination:
            lines.append(
                gettext(
                    'FlatOut 2: Top 3 je Heat qualifizieren sich jeweils für die nächste Runde.'
                )
            )
        else:
            lines.append(
                gettext(
                    'FFA Single Elimination: Die Qualifikanten je Heat werden automatisch aus der Heat-Verteilung der Folgerunde abgeleitet.'
                )
            )

        if preview.get('expected_final_heat_size'):
            lines.append(
                gettext(
                    'Erwartete Finalgröße: bis zu %(count)s Teilnehmer im letzten Heat.',
                    count=preview.get('expected_final_heat_size'),
                )
            )

        preliminary_round_summaries = preview.get('preliminary_round_summaries', [])
        if preliminary_round_summaries:
            lines.append(gettext('Vorrunden-Preview:'))
            for round_summary in preliminary_round_summaries:
                lines.append(
                    gettext(
                        'Vorrunde %(round_no)s: %(match_count)s Heats mit bis zu %(max_heat_size)s Teilnehmern',
                        round_no=round_summary.get('round_no'),
                        match_count=round_summary.get('match_count'),
                        max_heat_size=round_summary.get('max_heat_size'),
                    )
                )

        main_round_summaries = preview.get('main_round_summaries') or preview.get(
            'round_summaries', []
        )
        if main_round_summaries:
            lines.append(gettext('Main-Stage-Preview:'))
            for round_summary in main_round_summaries:
                lines.append(
                    gettext(
                        'Main Stage Runde %(round_no)s: %(match_count)s Heats mit bis zu %(max_heat_size)s Teilnehmern',
                        round_no=round_summary.get('round_no'),
                        match_count=round_summary.get('match_count'),
                        max_heat_size=round_summary.get('max_heat_size'),
                    )
                )

        if preview.get('preliminary_match_count') is not None:
            lines.append(
                gettext(
                    '%(count)s Vorrunden-Matches im aktuellen Preview',
                    count=preview.get('preliminary_match_count'),
                )
            )
        if preview.get('main_match_count') is not None:
            lines.append(
                gettext(
                    '%(count)s Main-Stage-Matches im aktuellen Preview',
                    count=preview.get('main_match_count'),
                )
            )
        return {'title': gettext('Aktuelle Builder-Vorschau'), 'lines': lines}

    if preview['participant_count'] <= main_stage_size:
        lines.append(
            gettext(
                'Mit der aktuellen Anzahl ready Teilnehmer ist keine Vorrunde nötig. Das Hauptturnier kann direkt erzeugt werden.'
            )
        )
    elif preliminary_type is None:
        lines.append(
            gettext(
                'Mit der aktuellen Anzahl ready Teilnehmer wäre eine Vorrunde nötig. Ohne Vorrunde würde die spätere Main-Stage-Generierung blockieren.'
            )
        )
    elif preliminary_type == StageType.round_robin_groups:
        if preview.get('round_robin_builder_mode') == 'manual_group_count':
            lines.append(
                gettext('Strategie: Expertenoption mit manueller Gruppenzahl')
            )
        else:
            lines.append(
                gettext(
                    'Strategie: Empfohlener Standard, bevorzugt 8 Gruppen / Top 2 bei Main Stage 16'
                )
            )
        lines.append(
            gettext('Gruppen: %(count)s', count=preview.get('group_count'))
        )
        group_sizes = preview.get('group_sizes', [])
        if group_sizes:
            lines.append(_format_group_distribution_summary(group_sizes))
            round_summary = _format_round_robin_global_round_summary(group_sizes)
            if round_summary is not None:
                lines.append(round_summary)
        qualifiers_per_group = preview.get('qualifiers_per_group')
        if qualifiers_per_group:
            lines.append(
                gettext(
                    'Qualifikation: Top %(top_n)s pro Gruppe -> %(size)s für das Hauptturnier',
                    top_n=qualifiers_per_group,
                    size=main_stage_size,
                )
            )
        lines.append(
            gettext(
                'Beim Erzeugen werden daraus echte Gruppen-Stages wie "Vorrunde Gruppe A", "Vorrunde Gruppe B" usw.'
            )
        )
        if preview.get('match_count') is not None:
            lines.append(
                gettext(
                    '%(count)s Vorrunden-Matches insgesamt',
                    count=preview['match_count'],
                )
            )
    elif preliminary_type == StageType.swiss:
        lines.append(
            gettext(
                'Swiss-Vorrunde: Schwelle %(threshold)s/%(threshold)s, %(round_count)s Runden, Qualifikation Top %(size)s insgesamt',
                threshold=preview.get('swiss_threshold'),
                round_count=preview.get('round_count'),
                size=main_stage_size,
            )
        )

    return {'title': gettext('Aktuelle Builder-Vorschau'), 'lines': lines}


def is_flatout2_stage_type(stage_type: StageType | None) -> bool:
    return stage_type == StageType.ffa_flatout2_single_elimination


def _get_flatout2_total_round_count(stage: Stage) -> int | None:
    raw_rounds = (stage.settings or {}).get('flatout2_rounds')
    if isinstance(raw_rounds, list):
        round_count = len(
            [raw_round for raw_round in raw_rounds if isinstance(raw_round, dict)]
        )
        if round_count > 0:
            return round_count

    try:
        round_count = int((stage.settings or {}).get('round_count') or 0)
    except (TypeError, ValueError):
        return None

    return round_count if round_count > 0 else None


def _get_flatout2_generation_action_label(
    stage_matches: list[Match],
) -> str:
    return (
        gettext('Stage neu vorbereiten')
        if stage_matches
        else gettext('Stage vorbereiten')
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
    action_label = gettext('Seeding / Matches generieren')
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
                'Diese FlatOut-2-Stage besteht aus einem einzelnen Finale und wird komplett manuell vorbereitet.'
            )
        elif total_round_count is not None and total_round_count > 1:
            action_hint = gettext(
                'Konfiguriert: %(count)s Runden. Diese FlatOut-2-Stage wird komplett manuell vorbereitet und bei Bedarf neu erzeugt.',
                count=total_round_count,
            )
        else:
            action_hint = gettext(
                'Diese FlatOut-2-Stage wird komplett manuell vorbereitet. Lege Runden, Matches, Rennen, Hosts und Teilnehmer direkt in der Stage fest.'
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
    raw_rounds = existing_stage_settings.get('flatout2_rounds')
    if not isinstance(raw_rounds, list):
        raw_rounds = []
    raw_match_blueprints = existing_stage_settings.get('flatout2_match_blueprints')
    if not isinstance(raw_match_blueprints, dict):
        raw_match_blueprints = {}

    try:
        max_players_per_match = int(
            existing_stage_settings.get('max_players_per_match') or 8
        )
    except (TypeError, ValueError):
        max_players_per_match = 8
    max_players_per_match = max(2, min(max_players_per_match, 8))

    participant_choices = [
        {'value': str(participant.id), 'label': participant.name}
        for participant in sorted(participants, key=lambda item: item.name.casefold())
    ]
    participant_choice_values = {choice['value'] for choice in participant_choices}
    max_match_count_per_round = 10
    round_count = 1

    round_defaults_by_no: dict[int, dict] = {}
    for index, raw_round in enumerate(raw_rounds, start=1):
        if not isinstance(raw_round, dict):
            continue
        try:
            round_no = int(raw_round.get('round_no') or index)
        except (TypeError, ValueError):
            round_no = index
        round_defaults_by_no[round_no] = raw_round

    rounds = []
    for round_no in (1,):
        default_round = round_defaults_by_no.get(round_no, {})
        posted_match_count = (
            (posted_form.get(f'flatout2_match_count_round_{round_no}') or '').strip()
            if posted_form is not None
            else ''
        )
        try:
            match_count = int(posted_match_count) if posted_match_count else 0
        except ValueError:
            match_count = 0
        if match_count < 1 or match_count > max_match_count_per_round:
            try:
                match_count = int(default_round.get('match_count') or 1)
            except (TypeError, ValueError):
                match_count = 1
        match_count = max(1, min(match_count, max_match_count_per_round))

        default_round_races = default_round.get('races')
        if not isinstance(default_round_races, list):
            default_round_races = []
        if not default_round_races:
            # Compatibility with older saved shape where races lived per match blueprint.
            legacy_blueprint = raw_match_blueprints.get(f'{round_no}:1')
            if isinstance(legacy_blueprint, dict):
                legacy_races = legacy_blueprint.get('races')
                if isinstance(legacy_races, list):
                    default_round_races = legacy_races

        posted_race_count = (
            (posted_form.get(f'flatout2_race_count_round_{round_no}') or '').strip()
            if posted_form is not None
            else ''
        )
        try:
            race_count = int(posted_race_count) if posted_race_count else 0
        except ValueError:
            race_count = 0
        if race_count < 1 or race_count > FLATOUT2_MAX_RACES_PER_ROUND:
            race_count = min(
                max(len(default_round_races), 1),
                FLATOUT2_MAX_RACES_PER_ROUND,
            )

        round_races = []
        for race_no in range(1, FLATOUT2_MAX_RACES_PER_ROUND + 1):
            default_race = (
                default_round_races[race_no - 1]
                if race_no - 1 < len(default_round_races)
                and isinstance(default_round_races[race_no - 1], dict)
                else {}
            )
            mode = (
                (posted_form.get(f'flatout2_mode_round_{round_no}_race_{race_no}') or '').strip()
                if posted_form is not None
                else str(default_race.get('mode') or 'single_race').strip()
            )
            if mode not in FLATOUT2_MODE_SPECS:
                mode = 'single_race'
            track = (
                (posted_form.get(f'flatout2_track_round_{round_no}_race_{race_no}') or '').strip()
                if posted_form is not None
                else str(default_race.get('track') or '').strip()
            )
            vehicle = (
                (posted_form.get(f'flatout2_vehicle_round_{round_no}_race_{race_no}') or '').strip()
                if posted_form is not None
                else str(default_race.get('vehicle') or '').strip()
            )
            round_races.append(
                {
                    'race_no': race_no,
                    'mode': mode,
                    'track': track,
                    'vehicle': vehicle,
                    'is_active': race_no <= race_count,
                }
            )

        matches = []
        for match_no in range(1, max_match_count_per_round + 1):
            match_key = f'{round_no}:{match_no}'
            blueprint = raw_match_blueprints.get(match_key)
            if not isinstance(blueprint, dict):
                blueprint = {}

            default_participant_ids = blueprint.get('participant_ids')
            if not isinstance(default_participant_ids, list):
                default_participant_ids = []
            selected_participant_ids = []
            for slot_no in range(1, max_players_per_match + 1):
                raw_value = (
                    (
                        posted_form.get(
                            f'flatout2_participant_round_{round_no}_match_{match_no}_slot_{slot_no}'
                        )
                        or ''
                    ).strip()
                    if posted_form is not None
                    else str(
                        default_participant_ids[slot_no - 1]
                        if slot_no - 1 < len(default_participant_ids)
                        and default_participant_ids[slot_no - 1]
                        else ''
                    ).strip()
                )
                if raw_value not in participant_choice_values:
                    raw_value = ''
                selected_participant_ids.append(raw_value)

            matches.append(
                {
                    'match_no': match_no,
                    'match_key': match_key,
                    'is_active': match_no <= match_count,
                    'participant_ids': selected_participant_ids,
                    'host_participant_id': (
                        selected_participant_ids[0]
                        if selected_participant_ids
                        else ''
                    ),
                }
            )

        rounds.append(
            {
                'round_no': round_no,
                'display_title': stage.name,
                'is_active': True,
                'match_count': match_count,
                'race_count': race_count,
                'races': round_races,
                'matches': matches,
            }
        )

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
    try:
        max_players_per_match = int(
            (stage.settings or {}).get('max_players_per_match') or 8
        )
    except (TypeError, ValueError):
        max_players_per_match = 8
    max_players_per_match = max(2, min(max_players_per_match, 8))
    max_match_count_per_round = 10
    round_count = 1

    rounds = []
    match_blueprints: dict[str, dict] = {}
    match_settings_by_round_and_match_no: dict[tuple[int, int], dict] = {}

    for round_no in (1,):
        raw_match_count = (
            request_form.get(f'flatout2_match_count_round_{round_no}') or ''
        ).strip()
        try:
            match_count = int(raw_match_count)
        except ValueError:
            match_count = 0
        if match_count < 1 or match_count > max_match_count_per_round:
            return Err(
                gettext(
                    'Bitte für Runde %(round_no)s eine Matchanzahl zwischen 1 und %(max_count)s wählen.',
                    round_no=round_no,
                    max_count=max_match_count_per_round,
                )
            )

        raw_race_count = (
            request_form.get(f'flatout2_race_count_round_{round_no}') or ''
        ).strip()
        try:
            race_count = int(raw_race_count)
        except ValueError:
            race_count = 0
        if race_count < 1 or race_count > FLATOUT2_MAX_RACES_PER_ROUND:
            return Err(
                gettext(
                    'Bitte für Runde %(round_no)s eine Rennanzahl zwischen 1 und %(max_count)s wählen.',
                    round_no=round_no,
                    max_count=FLATOUT2_MAX_RACES_PER_ROUND,
                )
            )

        round_races = []
        for race_no in range(1, race_count + 1):
            mode = (
                request_form.get(f'flatout2_mode_round_{round_no}_race_{race_no}')
                or ''
            ).strip()
            if mode not in FLATOUT2_MODE_SPECS:
                return Err(
                    gettext(
                        'Bitte für Runde %(round_no)s, Rennen %(race_no)s einen gültigen Modus wählen.',
                        round_no=round_no,
                        race_no=race_no,
                    )
                )
            track = (
                request_form.get(
                    f'flatout2_track_round_{round_no}_race_{race_no}'
                )
                or ''
            ).strip()
            vehicle = (
                request_form.get(
                    f'flatout2_vehicle_round_{round_no}_race_{race_no}'
                )
                or ''
            ).strip()
            if track not in FLATOUT2_TRACK_SET_BY_MODE[mode]:
                return Err(
                    gettext(
                        'Bitte für Runde %(round_no)s, Rennen %(race_no)s eine passende Strecke wählen.',
                        round_no=round_no,
                        race_no=race_no,
                    )
                )
            if vehicle not in FLATOUT2_VEHICLE_SET_BY_MODE[mode]:
                return Err(
                    gettext(
                        'Bitte für Runde %(round_no)s, Rennen %(race_no)s ein gültiges Fahrzeug wählen.',
                        round_no=round_no,
                        race_no=race_no,
                    )
                )
            round_races.append(
                {
                    'mode': mode,
                    'track': track,
                    'vehicle': vehicle,
                }
            )

        rounds.append(
            {
                'round_no': round_no,
                'display_title': stage.name,
                'match_count': match_count,
                'race_count': race_count,
                'races': round_races,
            }
        )

        assigned_participant_ids_for_round: set[str] = set()
        for match_no in range(1, match_count + 1):
            participant_ids_for_match: list[str | None] = []
            real_participant_ids_for_match: list[str] = []
            for slot_no in range(1, max_players_per_match + 1):
                raw_participant_id = (
                    request_form.get(
                        f'flatout2_participant_round_{round_no}_match_{match_no}_slot_{slot_no}'
                    )
                    or ''
                ).strip()
                if not raw_participant_id:
                    participant_ids_for_match.append(None)
                    continue
                if raw_participant_id not in participant_ids_by_str:
                    return Err(
                        gettext(
                            'Die Teilnehmerzuordnung für Runde %(round_no)s, Match %(match_no)s ist ungültig.',
                            round_no=round_no,
                            match_no=match_no,
                        )
                    )
                if raw_participant_id in real_participant_ids_for_match:
                    return Err(
                        gettext(
                            'Ein Teilnehmer darf in Runde %(round_no)s, Match %(match_no)s nur einmal vorkommen.',
                            round_no=round_no,
                            match_no=match_no,
                        )
                    )
                if raw_participant_id in assigned_participant_ids_for_round:
                    return Err(
                        gettext(
                            'Ein Teilnehmer darf in Runde %(round_no)s nur einem Match zugewiesen sein.',
                            round_no=round_no,
                        )
                    )
                participant_ids_for_match.append(raw_participant_id)
                real_participant_ids_for_match.append(raw_participant_id)
                assigned_participant_ids_for_round.add(raw_participant_id)

            host_participant_id = participant_ids_for_match[0]
            if real_participant_ids_for_match and host_participant_id is None:
                return Err(
                    gettext(
                        'In Runde %(round_no)s, Match %(match_no)s muss Slot 1 belegt sein, da Slot 1 immer der Host ist.',
                        round_no=round_no,
                        match_no=match_no,
                    )
                )

            match_key = f'{round_no}:{match_no}'
            match_blueprints[match_key] = {
                'participant_ids': participant_ids_for_match,
                'host_participant_id': host_participant_id,
            }
            match_settings_by_round_and_match_no[(round_no, match_no)] = {
                'host_participant_id': host_participant_id,
                'flatout2_races': round_races,
            }

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


