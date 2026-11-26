"""
byceps.services.netsession_tourney.blueprints.admin.routes_stage_participant_source_form
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The participant source settings shown on the stage create and update
forms (see `routes_stage_form`): taken from the stage settings and,
after a failed submit, from the posted form.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import request


_SELECTION_MODES = {'per_stage', 'per_group'}


@dataclass(frozen=True, kw_only=True)
class ParticipantSourceSelection:
    mode: str
    top_n: int
    selection_mode: str
    source_stage_ids: set[str]


def default_participant_source() -> ParticipantSourceSelection:
    return ParticipantSourceSelection(
        mode='tournament',
        top_n=1,
        selection_mode='per_stage',
        source_stage_ids=set(),
    )


def participant_source_from_settings(
    settings: dict[str, Any],
) -> ParticipantSourceSelection:
    selection_mode = str(settings.get('qualifier_selection_mode', 'per_stage'))
    if selection_mode not in _SELECTION_MODES:
        selection_mode = 'per_stage'

    return ParticipantSourceSelection(
        mode=str(settings.get('participant_source_mode', 'tournament')),
        top_n=_qualifier_top_n_from_settings(settings),
        selection_mode=selection_mode,
        source_stage_ids={
            str(source_stage_id)
            for source_stage_id in settings.get(
                'qualifier_source_stage_ids', []
            )
            if source_stage_id
        },
    )


def _qualifier_top_n_from_settings(settings: dict[str, Any]) -> int:
    raw_qualifier_top_n = settings.get('qualifier_top_n', 1)
    try:
        return max(1, int(raw_qualifier_top_n))
    except TypeError, ValueError:
        return 1


def apply_posted_participant_source(
    source: ParticipantSourceSelection,
) -> ParticipantSourceSelection:
    """Override the selection with the values of the posted form."""
    return ParticipantSourceSelection(
        mode=_posted_mode(source.mode),
        top_n=_posted_top_n(source.top_n),
        selection_mode=_posted_selection_mode(source.selection_mode),
        source_stage_ids=_posted_source_stage_ids(),
    )


def _posted_mode(default: str) -> str:
    posted_mode = (request.form.get('participant_source_mode') or '').strip()
    return posted_mode or default


def _posted_source_stage_ids() -> set[str]:
    return {
        source_stage_id
        for source_stage_id in request.form.getlist(
            'qualifier_source_stage_ids'
        )
        if source_stage_id
    }


def _posted_top_n(default: int) -> int:
    posted_top_n = (request.form.get('qualifier_top_n') or '').strip()
    if not posted_top_n:
        return default

    try:
        return max(1, int(posted_top_n))
    except ValueError:
        return default


def _posted_selection_mode(default: str) -> str:
    posted_selection_mode = (
        request.form.get('qualifier_selection_mode') or ''
    ).strip()
    if posted_selection_mode in _SELECTION_MODES:
        return posted_selection_mode

    return default


def participant_source_context(
    source: ParticipantSourceSelection,
) -> dict[str, Any]:
    return {
        'stage_source_mode': source.mode,
        'stage_qualifier_top_n': source.top_n,
        'stage_qualifier_selection_mode': source.selection_mode,
        'selected_source_stage_ids': source.source_stage_ids,
    }
