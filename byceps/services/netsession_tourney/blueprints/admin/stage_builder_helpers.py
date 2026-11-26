"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

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
)
from byceps.services.netsession_tourney.stage_service import (
    parse_source_stage_ids,
)


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
