"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_view_forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Stage selection, stage builder data and the Discord form of the
tournament detail page (see `routes_tournament_view`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import request
from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.route_config import (
    DISCORD_DM_EVENT_CHOICES,
    DISCORD_FORUM_EVENT_CHOICES,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_generation import (
    build_stage_generation_state,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_meta import (
    build_stage_builder_container_preview_meta,
    build_stage_builder_meta,
)
from byceps.services.netsession_tourney.forms import DiscordConfigForm
from byceps.services.netsession_tourney.logo_service import (
    get_discord_forum_image_choices,
)
from byceps.services.party.models import PartyID


def _parse_stage_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _get_default_stage(stage_tabs: list[Any], stages: list[Any]) -> Any:
    return stage_tabs[0] if stage_tabs else (stages[0] if stages else None)


def _find_stage(stages: list[Any], stage_id: UUID, default: Any) -> Any:
    return next(
        (stage for stage in stages if stage.id == stage_id),
        default,
    )


def select_stage(stages: list[Any], stage_tabs: list[Any]) -> Any:
    """Return the stage requested by the `stage_id` argument."""
    requested_stage_id = request.args.get('stage_id')
    selected_stage = _get_default_stage(stage_tabs, stages)
    if stages and requested_stage_id:
        requested_stage_uuid = _parse_stage_uuid(requested_stage_id)
        if requested_stage_uuid is not None:
            selected_stage = _find_stage(
                stages, requested_stage_uuid, selected_stage
            )
    return selected_stage


def collect_stage_builder_data(
    party_id: PartyID, tournament_id: Any, context: dict[str, Any]
) -> dict[str, Any]:
    """Return stage builder meta, generation state and preview meta."""
    stages = context['stages']
    stage_builder_meta_by_id = {
        stage.id: build_stage_builder_meta(stage) for stage in stages
    }
    stage_generation_state_by_id = {
        stage.id: build_stage_generation_state(
            stage,
            context['stages_by_id'],
            context['matches_by_stage_lookup'],
        )
        for stage in stages
    }
    stage_builder_container_preview_meta_by_id = {
        stage.id: preview_meta
        for stage in stages
        if (
            preview_meta := build_stage_builder_container_preview_meta(
                party_id, tournament_id, stage
            )
        )
        is not None
    }
    return {
        'stage_builder_meta_by_id': stage_builder_meta_by_id,
        'stage_generation_state_by_id': stage_generation_state_by_id,
        'stage_builder_container_preview_meta_by_id': (
            stage_builder_container_preview_meta_by_id
        ),
    }


def build_discord_form(party_id: PartyID, tournament: Any) -> DiscordConfigForm:
    """Return the Discord form filled with the tournament settings."""
    discord_form = DiscordConfigForm(
        data={
            'discord_enabled': tournament.discord_enabled,
            'forum_channel_id': tournament.discord_forum_channel_id,
            'discord_forum_image_url': tournament.discord_forum_image_url or '',
            'applied_tag_ids': ', '.join(tournament.discord_applied_tag_ids),
            'event_mask': tournament.discord_event_mask,
            'discord_dm_enabled': tournament.discord_dm_enabled,
            'discord_dm_event_mask': tournament.discord_dm_event_mask,
        }
    )
    discord_form.discord_forum_image_url.choices = [
        ('', gettext('Kein Discord-Forum-Bild ausgewählt'))
    ] + get_discord_forum_image_choices(party_id)
    discord_form.event_mask.choices = DISCORD_FORUM_EVENT_CHOICES
    discord_form.discord_dm_event_mask.choices = DISCORD_DM_EVENT_CHOICES
    return discord_form
