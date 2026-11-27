"""
byceps.services.netsession_tourney.blueprints.admin.routes_create_details_form
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks of the details step of the tournament creation wizard and the
wizard state it stores (see `routes_create_details`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    parse_csv,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_form_checks import (
    get_sponsor_logo_error,
    is_invalid_discord_forum_image_url,
    is_invalid_tournament_logo_url,
    stripped_or_none,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    slugify_tournament_title,
)
from byceps.services.netsession_tourney.discord_ids import is_discord_id
from byceps.services.netsession_tourney.discord_service_validation import (
    validate_discord_applied_tag_ids,
)
from byceps.services.party.models import PartyID
from byceps.util.framework.flash import flash_error


@dataclass(frozen=True, kw_only=True)
class DetailsSelection:
    tournament_logo_url: str | None
    is_sponsored: bool
    sponsor_logo_url: str | None
    discord_enabled: bool
    discord_forum_image_url: str | None
    discord_event_mask: list[Any]


def _get_discord_error(
    form: Any, discord_enabled: bool, discord_event_mask: list[Any]
) -> str | None:
    if not discord_enabled:
        return None
    forum_channel_id = (form.forum_channel_id.data or '').strip()
    if not forum_channel_id:
        return gettext('Bitte eine Discord-Forum-Channel-ID angeben.')
    if not discord_event_mask:
        return gettext('Bitte mindestens ein Discord-Forum-Event auswählen.')
    # Same checks as when Discord is configured after creation, so a
    # mistake shows up here and not after the tournament was created.
    if not is_discord_id(forum_channel_id):
        return gettext(
            'Die Discord-Forum-Channel-ID muss aus 17 bis 20 Ziffern bestehen.'
        )
    return validate_discord_applied_tag_ids(
        parse_csv(form.applied_tag_ids.data)
    )


def _get_logo_error(
    party_id: PartyID,
    tournament_logo_url: str | None,
    is_sponsored: bool,
    sponsor_logo_url: str | None,
) -> str | None:
    if is_invalid_tournament_logo_url(party_id, tournament_logo_url):
        return gettext('Ungültiges Turnierlogo ausgewählt.')
    return get_sponsor_logo_error(party_id, is_sponsored, sponsor_logo_url)


def _get_discord_image_error(
    party_id: PartyID, discord_forum_image_url: str | None
) -> str | None:
    if is_invalid_discord_forum_image_url(party_id, discord_forum_image_url):
        return gettext('Das ausgewählte Discord-Forum-Bild ist ungültig.')
    return None


def parse_details_selection(
    party_id: PartyID, form: Any
) -> DetailsSelection | None:
    """Check logos and Discord fields; flash the error and return `None`."""
    tournament_logo_url = stripped_or_none(form.tournament_logo_url.data)
    is_sponsored = bool(form.is_sponsored.data)
    sponsor_logo_url = stripped_or_none(form.sponsor_logo_url.data)
    error = _get_logo_error(
        party_id, tournament_logo_url, is_sponsored, sponsor_logo_url
    )
    if error is not None:
        flash_error(error)
        return None

    discord_enabled = bool(form.discord_enabled.data)
    discord_forum_image_url = stripped_or_none(
        form.discord_forum_image_url.data
    )
    discord_event_mask = list(form.event_mask.data or [])
    error = _get_discord_image_error(
        party_id, discord_forum_image_url
    ) or _get_discord_error(form, discord_enabled, discord_event_mask)
    if error is not None:
        flash_error(error)
        return None

    return DetailsSelection(
        tournament_logo_url=tournament_logo_url,
        is_sponsored=is_sponsored,
        sponsor_logo_url=sponsor_logo_url,
        discord_enabled=discord_enabled,
        discord_forum_image_url=discord_forum_image_url,
        discord_event_mask=discord_event_mask,
    )


def build_details_state(
    form: Any, selection: DetailsSelection
) -> dict[str, Any]:
    """Return the wizard state of the details step."""
    slug = form.slug.data.strip()
    if not slug:
        slug = slugify_tournament_title(form.title.data)

    return {
        'slug': slug,
        'title': form.title.data.strip(),
        'subtitle': stripped_or_none(form.subtitle.data),
        'logo_url': selection.tournament_logo_url,
        'is_sponsored': selection.is_sponsored,
        'sponsor_logo_url': selection.sponsor_logo_url
        if selection.is_sponsored
        else None,
        'game': stripped_or_none(form.game.data),
        'rules_page_slug': stripped_or_none(form.rules_template_slug.data),
        'discord_enabled': selection.discord_enabled,
        'discord_forum_channel_id': stripped_or_none(
            form.forum_channel_id.data
        ),
        'discord_forum_image_url': selection.discord_forum_image_url,
        'discord_applied_tag_ids': parse_csv(form.applied_tag_ids.data),
        'discord_event_mask': selection.discord_event_mask,
    }
