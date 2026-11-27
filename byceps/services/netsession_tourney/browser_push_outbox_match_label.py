"""
byceps.services.netsession_tourney.browser_push_outbox_match_label
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The match label shown in browser push messages.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from byceps.database import db

from .dbmodels import (
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyStage,
)
from .models import (
    MatchID,
    StageType,
)
from .notification_labels import (
    build_double_elimination_notification_match_label,
)


_GENERIC_STAGE_NAMES = {'match', 'matches'}


# The database column holds the enum value, not the enum member.
_DOUBLE_ELIMINATION_STAGE_TYPE_VALUES = frozenset(
    {
        StageType.double_elimination.value,
        StageType.double_elimination_double_grand_final.value,
    }
)


def build_browser_push_match_label(payload: dict[str, Any]) -> str | None:
    db_match = _find_browser_push_match(payload)
    if db_match is None:
        return None

    db_stage = db.session.get(DbNetsessionTourneyStage, db_match.stage_id)
    if db_stage is None:
        return f'M #{db_match.match_no}'

    if db_stage.type in _DOUBLE_ELIMINATION_STAGE_TYPE_VALUES:
        return build_double_elimination_notification_match_label(
            db_match, db_stage.id
        )

    return _build_stage_titled_match_label(db_match, db_stage)


def _find_browser_push_match(
    payload: dict[str, Any],
) -> DbNetsessionTourneyMatch | None:
    match_id = payload.get('match_id')
    if not isinstance(match_id, str) or not match_id:
        return None

    try:
        parsed_match_id = MatchID(UUID(match_id))
    except ValueError:
        return None

    return db.session.get(DbNetsessionTourneyMatch, parsed_match_id)


def _build_stage_titled_match_label(
    db_match: DbNetsessionTourneyMatch, db_stage: DbNetsessionTourneyStage
) -> str:
    stage_settings = db_stage.settings_json or {}
    builder_display_title = str(
        stage_settings.get('builder_display_title') or ''
    ).strip()
    if builder_display_title:
        return f'{builder_display_title} • M #{db_match.match_no}'

    if db_stage.name:
        stage_name = db_stage.name.strip()
        if stage_name.lower() not in _GENERIC_STAGE_NAMES:
            return f'{stage_name} • M #{db_match.match_no}'

    return f'M #{db_match.match_no}'
