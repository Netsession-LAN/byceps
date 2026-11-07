"""
byceps.services.netsession_tourney.blueprints.site.stage_render_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from collections import defaultdict

from flask_babel import gettext

from ...models import StageType
from . import builder_helpers
from .bracket_helpers import build_bracket_sections, build_bracket_data
from .builder_display_helpers import (
    get_builder_main_display_stages,
    get_flatout2_builder_bracket_display_stages,
)
from .builder_helpers import (
    build_pending_builder_round_summary_lines,
    get_builder_container_child_stages,
    get_materialized_builder_container_stages,
    has_materialized_builder_container_stage,
)
from .ffa_single_elimination_rendering import get_ffa_single_elimination_round_title
from .flatout2_public_rendering import (
    build_flatout2_bracket_section,
    build_flatout2_match_section,
)
from .match_helpers import (
    build_match_labels,
    _parse_slot_scores,
)
from .presentation_helpers import (
    _build_round_time_range_label,
    combine_stage_section_title,
    get_stage_duration_minutes,
)
from .stage_filters import (
    _is_ffa_scoring_stage,
    is_ffa_single_elimination_stage,
    _is_flatout2_stage,
)
from .round_based_public_rendering import build_match_overview_sections
from .round_based_public_rendering import _get_score_display
from ...score_parsing import get_ffa_points_per_kill


def _group_matches_by_round(matches):
    grouped = defaultdict(list)
    for match in matches:
        grouped[match.round_no].append(match)

    return [
        {'round_no': round_no, 'matches': grouped[round_no]}
        for round_no in sorted(grouped.keys())
    ]


def build_ffa_match_sections(
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    match_labels_by_id,
    skipped_match_ids,
    stages_by_id,
):
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    stage_duration_minutes_by_id = {
        stage_id: get_stage_duration_minutes(stage)
        for stage_id, stage in stages_by_id.items()
    }

    sections = []
    for stage_id, stage_matches in sorted(
        matches_by_stage_id.items(),
        key=lambda item: (
            stages_by_id.get(item[0]).order_no if stages_by_id.get(item[0]) else 999,
            stages_by_id.get(item[0]).name if stages_by_id.get(item[0]) else '',
        ),
    ):
        stage = stages_by_id.get(stage_id)
        if _is_flatout2_stage(stage):
            sections.append(
                build_flatout2_match_section(
                    stage,
                    stage_matches,
                    slots_by_match_id,
                    results_by_match_id,
                    participants_by_id,
                    users_by_id,
                    match_labels_by_id,
                    skipped_match_ids,
                    stage_duration_minutes_by_id,
                    group_matches_by_round=_group_matches_by_round,
                    build_participant_data=_build_ffa_match_participant_data,
                    parse_slot_scores=_parse_slot_scores,
                    get_placement_by_slot_no=_get_ffa_placement_by_slot_no,
                    get_score_display=_get_score_display,
                    build_round_time_range_label=_build_round_time_range_label,
                )
            )
            continue

        grouped_rounds = _group_matches_by_round(stage_matches)
        is_ffa_single_elimination = (
            stage is not None
            and stage.type
            in {
                StageType.ffa_single_elimination,
            }
        )
        try:
            total_round_count = int((stage.settings or {}).get('round_count') or 0)
        except (AttributeError, TypeError, ValueError):
            total_round_count = 0
        builder_display_title = str(
            (stage.settings or {}).get('builder_display_title') or ''
        ).strip()
        round_count = len(grouped_rounds)
        rounds = []
        for round_index, round_data in enumerate(grouped_rounds):
            matches_in_round = sorted(
                round_data['matches'],
                key=lambda match: match.match_no,
            )
            rows = []
            for match in matches_in_round:
                slots = sorted(
                    slots_by_match_id.get(match.id, []),
                    key=lambda slot: slot.slot_no,
                )
                result = results_by_match_id.get(match.id)
                slot_scores = _parse_slot_scores(slots, result)
                placement_by_slot_no = _get_ffa_placement_by_slot_no(
                    result, slots
                )
                participants = [
                    _build_ffa_match_participant_data(
                        slot,
                        participants_by_id,
                        users_by_id,
                        result.winner_slot if result else None,
                        slot_scores.get(slot.slot_no),
                        placement_by_slot_no.get(slot.slot_no),
                    )
                    for slot in slots
                    if slot.participant_id is not None
                ]
                participants.sort(
                    key=lambda participant: (
                        participant['placement']
                        if participant['placement'] is not None
                        else 999999,
                        -participant['kills_value'],
                        participant['slot_no'],
                        participant['name'].lower(),
                    )
                )
                rows.append(
                    {
                        'match': match,
                        'match_label': match_labels_by_id.get(
                            match.id,
                            f'{gettext("Match")} #{match.match_no}',
                        ),
                        'participants': participants,
                        'score_display': _get_score_display(result),
                        'has_result': result is not None and result.winner_slot is not None,
                        'is_struck': match.id in skipped_match_ids,
                        'show_kills': True,
                        'host_participant_id': '',
                        'host_name': None,
                        'round_races': [],
                    }
                )

            rounds.append(
                {
                    'round_no': round_data['round_no'],
                    'display_round_no': round_data['round_no'],
                    'display_title': (
                        builder_display_title
                        or get_ffa_single_elimination_round_title(
                            round_index,
                            round_count,
                            stage_type=stage.type if stage is not None else None,
                            round_no=round_data['round_no'],
                            total_round_count=total_round_count or None,
                        )
                        if is_ffa_single_elimination
                        else None
                    ),
                    'time_range_label': _build_round_time_range_label(
                        matches_in_round,
                        stage_duration_minutes_by_id,
                    ),
                    'rows': rows,
                }
            )

        sections.append(
            {
                'key': str(stage_id),
                'title': stage.name if stage is not None else None,
                'presentation': 'ffa',
                'rounds': rounds,
            }
        )

    return sections


def build_ffa_single_elimination_bracket_sections(
    matches,
    slots_by_match_id,
    results_by_match_id,
    match_labels_by_id,
    stages_by_id,
):
    source_match_id_by_slot_id = {}
    for slots in slots_by_match_id.values():
        for slot in slots:
            source_match_id_by_slot_id[slot.id] = slot.match_id

    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    sections = []
    only_flatout2_stages = True
    for stage_id, stage_matches in sorted(
        matches_by_stage_id.items(),
        key=lambda item: (
            stages_by_id.get(item[0]).order_no if stages_by_id.get(item[0]) else 999,
            stages_by_id.get(item[0]).name if stages_by_id.get(item[0]) else '',
        ),
    ):
        stage = stages_by_id.get(stage_id)
        is_flatout2_stage = _is_flatout2_stage(stage)
        only_flatout2_stages = only_flatout2_stages and is_flatout2_stage
        if is_flatout2_stage:
            sections.append(
                build_flatout2_bracket_section(
                    stage,
                    stage_matches,
                    slots_by_match_id,
                    results_by_match_id,
                    match_labels_by_id,
                    group_matches_by_round=_group_matches_by_round,
                    source_match_id_by_slot_id=source_match_id_by_slot_id,
                    get_score_display=_get_score_display,
                )
            )
            continue

        grouped_rounds = _group_matches_by_round(stage_matches)
        round_count = len(grouped_rounds)
        try:
            total_round_count = int((stage.settings or {}).get('round_count') or 0)
        except (AttributeError, TypeError, ValueError):
            total_round_count = 0
        builder_display_title = str(
            (stage.settings or {}).get('builder_display_title') or ''
        ).strip()
        rounds = []
        for round_index, round_data in enumerate(grouped_rounds):
            items = []
            for index, match in enumerate(
                sorted(round_data['matches'], key=lambda item: item.match_no)
            ):
                slots = sorted(
                    slots_by_match_id.get(match.id, []),
                    key=lambda slot: slot.slot_no,
                )
                result = results_by_match_id.get(match.id)
                source_match_ids = []
                for slot in slots:
                    if slot.source_match_slot_id is None:
                        continue
                    source_match_id = source_match_id_by_slot_id.get(
                        slot.source_match_slot_id
                    )
                    if (
                        source_match_id is not None
                        and source_match_id not in source_match_ids
                    ):
                        source_match_ids.append(source_match_id)

                items.append(
                    {
                        'match': match,
                        'match_label': match_labels_by_id.get(
                            match.id,
                            f'{gettext("Match")} #{match.match_no}',
                        ),
                        'participant_count': len(
                            [
                                slot
                                for slot in slots
                                if slot.participant_id is not None
                            ]
                        ),
                        'slot_capacity': len(slots),
                        'source_match_ids': source_match_ids,
                        'has_result': (
                            result is not None
                            and result.winner_slot is not None
                        ),
                        'score_display': _get_score_display(result),
                        'round_match_index': index,
                        'host_name': None,
                    }
                )

            rounds.append(
                {
                    'round_no': round_data['round_no'],
                    'display_round_no': round_data.get(
                        'display_round_no', round_data['round_no']
                    ),
                    'display_title': (
                        get_ffa_single_elimination_round_title(
                            round_index,
                            round_count,
                            stage_type=stage.type if stage is not None else None,
                            round_no=round_data['round_no'],
                            total_round_count=total_round_count or None,
                        )
                        if not builder_display_title
                        else builder_display_title
                    ),
                    'matches': items,
                }
            )

        sections.append(
            {
                'key': str(stage_id),
                'title': stage.name if stage is not None else None,
                'presentation': 'ffa',
                'rounds': rounds,
            }
        )

    if sections and only_flatout2_stages:
        merged_rounds = []
        display_round_no = 1
        for section in sections:
            section_title = section.get('title')
            for round_data in section.get('rounds', []):
                merged_rounds.append(
                    {
                        'round_no': display_round_no,
                        'display_round_no': display_round_no,
                        'display_title': round_data.get('display_title')
                        or section_title
                        or gettext('Runde %(round_no)s', round_no=display_round_no),
                        'matches': [
                            {
                                **item,
                                'round_match_index': index,
                            }
                            for index, item in enumerate(
                                round_data.get('matches', [])
                            )
                        ],
                    }
                )
                display_round_no += 1

        return [
            {
                'key': 'flatout2-bracket',
                'title': None,
                'presentation': 'flatout2',
                'rounds': merged_rounds,
            }
        ]

    return sections


def _build_ffa_match_participant_data(
    slot,
    participants_by_id,
    users_by_id,
    winner_slot: int | None,
    kills: str | None,
    placement: int | None,
    points: int | None = None,
    *,
    is_host: bool = False,
) -> dict:
    participant = participants_by_id.get(slot.participant_id)
    image_url = None
    image_alt = None
    if participant and participant.type.value == 'team' and participant.logo_url:
        image_url = participant.logo_url
        image_alt = gettext('Team-Logo')
    elif participant and participant.user_id is not None:
        user = users_by_id.get(participant.user_id)
        if user is not None and user.avatar_url:
            image_url = user.avatar_url
            image_alt = gettext('Avatar')

    return {
        'slot_no': slot.slot_no,
        'name': participant.name if participant is not None else gettext('offen'),
        'participant': participant,
        'image_url': image_url,
        'image_alt': image_alt,
        'kills': kills or '-',
        'kills_value': _parse_score_int(kills),
        'placement': placement,
        'points': points if points is not None else 0,
        'is_winner': winner_slot is not None and slot.slot_no == winner_slot,
        'is_host': is_host,
    }

def build_ffa_match_detail_rows(
    slots,
    participants_by_id,
    users_by_id,
    result,
    slot_scores,
    *,
    is_flatout2_match: bool = False,
):
    placement_by_slot_no = _get_ffa_placement_by_slot_no(result, slots)
    points_by_slot_no = _get_ffa_points_by_slot_no(result, slots)
    rows = [
        _build_ffa_match_participant_data(
            slot,
            participants_by_id,
            users_by_id,
            result.winner_slot if result else None,
            slot_scores.get(slot.slot_no),
            placement_by_slot_no.get(slot.slot_no),
            points_by_slot_no.get(slot.slot_no),
        )
        for slot in slots
        if slot.participant_id is not None
    ]
    if is_flatout2_match:
        rows.sort(
            key=lambda row: (
                row['placement'] if row['placement'] is not None else 999999,
                -row['points'],
                row['slot_no'],
                row['name'].lower(),
            )
        )
    else:
        rows.sort(
            key=lambda row: (
                row['placement'] if row['placement'] is not None else 999999,
                -row['kills_value'],
                row['slot_no'],
                row['name'].lower(),
            )
        )
    return rows


def _get_ffa_placement_by_slot_no(result, slots) -> dict[int, int]:
    if result is None or not isinstance(result.ranking, dict):
        return {}

    raw_placements = result.ranking.get('placements')
    if not isinstance(raw_placements, dict):
        return {}

    placements = {}
    for slot in slots:
        raw_value = raw_placements.get(str(slot.slot_no))
        if raw_value is None:
            raw_value = raw_placements.get(slot.slot_no)
        try:
            placements[slot.slot_no] = int(raw_value)
        except (TypeError, ValueError):
            continue

    return placements


def _get_ffa_points_by_slot_no(result, slots) -> dict[int, int]:
    if result is None or not isinstance(result.ranking, dict):
        return {}

    raw_points = result.ranking.get('points')
    if not isinstance(raw_points, dict):
        return {}

    points = {}
    for slot in slots:
        raw_value = raw_points.get(str(slot.slot_no))
        if raw_value is None:
            raw_value = raw_points.get(slot.slot_no)
        try:
            points[slot.slot_no] = int(raw_value)
        except (TypeError, ValueError):
            continue

    return points


def _parse_score_int(value: str | None) -> int:
    try:
        return int(value or '0')
    except (TypeError, ValueError):
        return 0


def _build_stage_public_match_sections(
    stage,
    stage_matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
    stages_by_id,
):
    if not stage_matches:
        if _is_flatout2_stage(stage):
            return builder_helpers._build_flatout2_placeholder_match_sections(stage)
        return []

    if is_ffa_single_elimination_stage(stage):
        return build_ffa_match_sections(
            stage_matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            match_labels_by_id,
            skipped_match_ids,
            stages_by_id,
        )

    stage_bracket = build_bracket_data(
        stage_matches,
        slots_by_match_id,
        participants_by_id,
    )
    return build_match_overview_sections(
        build_bracket_sections(stage_bracket, match_labels_by_id),
        stages_by_id,
        results_by_match_id,
        slot_scores_by_match_id,
        match_labels_by_id,
        users_by_id,
        skipped_match_ids,
    )


def _build_stage_public_bracket_sections(
    stage,
    stage_matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    match_labels_by_id,
    stages_by_id,
):
    if not stage_matches:
        if _is_flatout2_stage(stage):
            return builder_helpers._build_flatout2_placeholder_bracket_sections(stage)
        return []

    if is_ffa_single_elimination_stage(stage):
        return build_ffa_single_elimination_bracket_sections(
            stage_matches,
            slots_by_match_id,
            results_by_match_id,
            match_labels_by_id,
            stages_by_id,
        )

    stage_bracket = build_bracket_data(
        stage_matches,
        slots_by_match_id,
        participants_by_id,
    )
    return build_bracket_sections(stage_bracket, match_labels_by_id)


def _build_builder_stage_match_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
):
    if not has_materialized_builder_container_stage(stages):
        return []

    stages_by_id = {stage.id: stage for stage in stages}
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    sections = []
    for container_stage in get_materialized_builder_container_stages(stages):
        child_stages = get_builder_container_child_stages(stages, container_stage)
        if not child_stages:
            continue

        for child_stage in child_stages:
            stage_matches = matches_by_stage_id.get(child_stage.id, [])
            stage_match_sections = _build_stage_public_match_sections(
                child_stage,
                stage_matches,
                slots_by_match_id,
                results_by_match_id,
                participants_by_id,
                users_by_id,
                slot_scores_by_match_id,
                match_labels_by_id,
                skipped_match_ids,
                stages_by_id,
            )
            if not stage_match_sections:
                sections.append(
                    {
                        'kind': 'summary',
                        'key': f'pending-{child_stage.id}',
                        'title': child_stage.name,
                        'presentation': 'summary',
                        'lines': build_pending_builder_round_summary_lines(
                            child_stage
                        ),
                    }
                )
                continue
            for subsection in stage_match_sections:
                subsection_title = subsection.get('title')
                if subsection_title == child_stage.name:
                    subsection_title = None
                sections.append(
                    {
                        'kind': 'matches',
                        'key': f'{child_stage.id}-{subsection["key"]}',
                        'title': combine_stage_section_title(
                            child_stage.name, subsection_title
                        ),
                        'presentation': subsection.get('presentation', 'duel'),
                        'rounds': subsection['rounds'],
                    }
                )

    return sections


def _build_builder_stage_bracket_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
):
    if not has_materialized_builder_container_stage(stages):
        return []

    stages_by_id = {stage.id: stage for stage in stages}
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    sections = []
    for container_stage in get_materialized_builder_container_stages(stages):
        child_stages = get_builder_container_child_stages(stages, container_stage)
        if not child_stages:
            continue

        for child_stage in child_stages:
            if child_stage.type == StageType.round_robin_groups:
                continue

            stage_matches = matches_by_stage_id.get(child_stage.id, [])
            stage_sections = _build_stage_public_bracket_sections(
                child_stage,
                stage_matches,
                slots_by_match_id,
                results_by_match_id,
                participants_by_id,
                match_labels_by_id,
                stages_by_id,
            )
            if not stage_sections:
                sections.append(
                    {
                        'kind': 'summary',
                        'key': f'pending-{child_stage.id}',
                        'title': child_stage.name,
                        'lines': build_pending_builder_round_summary_lines(
                            child_stage
                        ),
                    }
                )
                continue
            for subsection in stage_sections:
                subsection_title = subsection.get('title')
                if subsection_title == child_stage.name:
                    subsection_title = None
                sections.append(
                    {
                        'kind': 'bracket',
                        'key': f'{child_stage.id}-{subsection["key"]}',
                        'title': combine_stage_section_title(
                            child_stage.name, subsection_title
                        ),
                        'rounds': subsection['rounds'],
                    }
                )

    return sections

def build_builder_preliminary_match_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
):
    preliminary_containers = get_materialized_builder_container_stages(
        stages, role='preliminary'
    )
    if not preliminary_containers:
        return []

    stages_by_id = {stage.id: stage for stage in stages}
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    sections = []
    for container_stage in preliminary_containers:
        for stage in get_builder_container_child_stages(stages, container_stage):
            stage_matches = matches_by_stage_id.get(stage.id, [])
            if not stage_matches:
                sections.append(
                    {
                        'kind': 'summary',
                        'key': str(stage.id),
                        'title': stage.name,
                        'presentation': 'summary',
                        'lines': build_pending_builder_round_summary_lines(
                            stage
                        ),
                    }
                )
                continue

            stage_match_sections = _build_stage_public_match_sections(
                stage,
                stage_matches,
                slots_by_match_id,
                results_by_match_id,
                participants_by_id,
                users_by_id,
                slot_scores_by_match_id,
                match_labels_by_id,
                skipped_match_ids,
                stages_by_id,
            )
            if not stage_match_sections:
                continue

            combined_rounds = []
            presentation = 'duel'
            for subsection in stage_match_sections:
                combined_rounds.extend(subsection['rounds'])
                presentation = subsection.get('presentation', presentation)

            sections.append(
                {
                    'kind': 'matches',
                    'key': str(stage.id),
                    'title': stage.name,
                    'presentation': presentation,
                    'rounds': combined_rounds,
                }
            )

    return sections


def build_builder_main_stage_match_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    users_by_id,
    slot_scores_by_match_id,
    match_labels_by_id,
    skipped_match_ids,
):
    main_stages = get_builder_main_display_stages(stages)
    if not main_stages:
        return []

    stages_by_id = {stage.id: stage for stage in stages}
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    sections = []
    for stage in main_stages:
        stage_matches = matches_by_stage_id.get(stage.id, [])
        stage_sections = _build_stage_public_match_sections(
            stage,
            stage_matches,
            slots_by_match_id,
            results_by_match_id,
            participants_by_id,
            users_by_id,
            slot_scores_by_match_id,
            match_labels_by_id,
            skipped_match_ids,
            stages_by_id,
        )
        if not stage_sections:
            sections.append(
                {
                    'kind': 'summary',
                    'key': f'pending-{stage.id}',
                    'title': stage.name,
                    'presentation': 'summary',
                    'lines': build_pending_builder_round_summary_lines(stage),
                }
            )
            continue

        sections.extend(stage_sections)

    return sections


def build_builder_main_stage_bracket_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
):
    main_stages = get_builder_main_display_stages(stages)
    if not main_stages:
        return []

    stages_by_id = {stage.id: stage for stage in stages}
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    sections = []
    for stage in main_stages:
        stage_matches = matches_by_stage_id.get(stage.id, [])
        stage_match_ids = {match.id for match in stage_matches}
        stage_slots_by_match_id = {
            match_id: slots_by_match_id.get(match_id, [])
            for match_id in stage_match_ids
        }
        stage_participant_ids = {
            slot.participant_id
            for slots in stage_slots_by_match_id.values()
            for slot in slots
            if slot.participant_id is not None
        }
        stage_participants_by_id = {
            participant_id: participants_by_id[participant_id]
            for participant_id in stage_participant_ids
            if participant_id in participants_by_id
        }
        stage_match_labels_by_id = build_match_labels(
            stage_matches,
            stage_slots_by_match_id,
            stages_by_id,
        )
        stage_sections = _build_stage_public_bracket_sections(
            stage,
            stage_matches,
            stage_slots_by_match_id,
            results_by_match_id,
            stage_participants_by_id,
            stage_match_labels_by_id,
            stages_by_id,
        )
        if not stage_sections:
            sections.append(
                {
                    'kind': 'summary',
                    'key': f'pending-{stage.id}',
                    'title': stage.name,
                    'lines': build_pending_builder_round_summary_lines(stage),
                }
            )
            continue

        for subsection in stage_sections:
            subsection_title = subsection.get('title')
            if subsection_title == stage.name:
                subsection_title = None
            sections.append(
                {
                    'kind': 'bracket',
                    'key': f'{stage.id}-{subsection["key"]}',
                    'title': combine_stage_section_title(
                        stage.name, subsection_title
                    ),
                    'presentation': (
                        'ffa'
                        if is_ffa_single_elimination_stage(stage)
                        else 'duel'
                    ),
                    'match_labels_by_id': stage_match_labels_by_id,
                    'rounds': subsection['rounds'],
                }
            )

    return sections

def _build_flatout2_builder_full_bracket_sections(
    stages,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
):
    display_stages = get_flatout2_builder_bracket_display_stages(stages)
    if not display_stages:
        return []

    stages_by_id = {stage.id: stage for stage in stages}
    matches_by_stage_id = defaultdict(list)
    for match in matches:
        matches_by_stage_id[match.stage_id].append(match)

    merged_rounds = []
    for stage in display_stages:
        stage_matches = matches_by_stage_id.get(stage.id, [])
        stage_match_ids = {match.id for match in stage_matches}
        stage_slots_by_match_id = {
            match_id: slots_by_match_id.get(match_id, [])
            for match_id in stage_match_ids
        }
        stage_participant_ids = {
            slot.participant_id
            for slots in stage_slots_by_match_id.values()
            for slot in slots
            if slot.participant_id is not None
        }
        stage_participants_by_id = {
            participant_id: participants_by_id[participant_id]
            for participant_id in stage_participant_ids
            if participant_id in participants_by_id
        }
        stage_match_labels_by_id = build_match_labels(
            stage_matches,
            stage_slots_by_match_id,
            stages_by_id,
        )
        stage_sections = _build_stage_public_bracket_sections(
            stage,
            stage_matches,
            stage_slots_by_match_id,
            results_by_match_id,
            stage_participants_by_id,
            stage_match_labels_by_id,
            stages_by_id,
        )
        if not stage_sections:
            continue

        for subsection in stage_sections:
            merged_rounds.extend(subsection['rounds'])

    if not merged_rounds:
        return []

    return [
        {
            'kind': 'bracket',
            'key': 'flatout2-builder-full',
            'title': None,
            'presentation': 'ffa',
            'rounds': merged_rounds,
        }
    ]


def build_team_history_rows(
    team,
    matches,
    slots_by_match_id,
    results_by_match_id,
    participants_by_id,
    match_labels_by_id,
    stages_by_id,
):
    history_rows = []
    for match in matches:
        slots = slots_by_match_id.get(match.id, [])
        own_slot = next(
            (
                slot
                for slot in slots
                if slot.participant_id is not None and slot.participant_id == team.id
            ),
            None,
        )
        if own_slot is None:
            continue

        opponents = [
            participants_by_id.get(slot.participant_id)
            for slot in slots
            if slot.participant_id is not None and slot.participant_id != team.id
        ]
        stage = stages_by_id.get(match.stage_id)
        result = results_by_match_id.get(match.id)
        outcome = 'pending'
        if result and result.winner_slot is not None:
            outcome = 'win' if result.winner_slot == own_slot.slot_no else 'loss'

        is_ffa_scoring_match = _is_ffa_scoring_stage(stage)
        is_flatout2_match = _is_flatout2_stage(stage)
        placement = None
        points = 0
        total_points = 0
        if is_ffa_scoring_match:
            placement = _get_ffa_placement_by_slot_no(result, slots).get(
                own_slot.slot_no
            )
            points = _get_ffa_points_by_slot_no(result, slots).get(
                own_slot.slot_no, 0
            )
            raw_score_slots = {}
            if result and isinstance(result.score.get('slots'), dict):
                raw_score_slots = result.score.get('slots')
            raw_kills = raw_score_slots.get(str(own_slot.slot_no))
            if raw_kills is None:
                raw_kills = raw_score_slots.get(own_slot.slot_no)
            kills = _parse_score_int(raw_kills)
            points_per_kill = get_ffa_points_per_kill(
                stage.settings if stage is not None else {}
            )
            total_points = points + (kills * points_per_kill)

        history_rows.append(
            {
                'match': match,
                'is_ffa_scoring_match': is_ffa_scoring_match,
                'is_flatout2_match': is_flatout2_match,
                'match_label': match_labels_by_id.get(
                    match.id, f'{gettext("Match")} #{match.match_no}'
                ),
                'own_slot': own_slot,
                'opponents': [opponent for opponent in opponents if opponent],
                'result': result,
                'outcome': outcome,
                'left_team_name': _get_team_name_for_slot(
                    slots, 1, participants_by_id
                ),
                'right_team_name': _get_team_name_for_slot(
                    slots, 2, participants_by_id
                ),
                'score_display': _get_score_display(result),
                'score_left': _get_score_side(result, 0),
                'score_right': _get_score_side(result, 1),
                'left_is_own_team': own_slot.slot_no == 1,
                'right_is_own_team': own_slot.slot_no == 2,
                'left_is_bye': _is_bye_slot(slots, 1),
                'right_is_bye': _is_bye_slot(slots, 2),
                'placement': placement,
                'points': points,
                'total_points': total_points,
            }
        )

    return history_rows


def _get_team_name_for_slot(slots, slot_no: int, participants_by_id) -> str:
    slot = next((item for item in slots if item.slot_no == slot_no), None)
    if slot is None:
        return '-'

    if slot.participant_id is None:
        return gettext('Freilos')

    participant = participants_by_id.get(slot.participant_id)
    if participant is None:
        return gettext('offen')

    return participant.name


def _is_bye_slot(slots, slot_no: int) -> bool:
    slot = next((item for item in slots if item.slot_no == slot_no), None)
    if slot is None:
        return False

    return slot.participant_id is None


def _get_score_side(result, index: int) -> str | None:
    score_display = _get_score_display(result)
    if score_display == '-' or ':' not in score_display:
        return None

    parts = score_display.split(':', 1)
    if len(parts) != 2:
        return None

    return parts[index].strip()

