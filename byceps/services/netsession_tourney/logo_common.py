"""
byceps.services.netsession_tourney.logo_common
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shared limits, labels and paths of the logo and image assets.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from pathlib import Path

from byceps.byceps_app import get_current_byceps_app
from byceps.services.party.models import PartyID
from byceps.util.image.dimensions import Dimensions
from byceps.util.image.image_type import ImageType


# Uploads: no SVG (may contain scripts); existing SVG files stay usable.
ALLOWED_IMAGE_TYPES = frozenset(
    [
        ImageType.jpeg,
        ImageType.png,
        ImageType.webp,
    ]
)


MAXIMUM_DIMENSIONS = Dimensions(512, 512)


MAXIMUM_BANNER_DIMENSIONS = Dimensions(1200, 300)


ALLOWED_SUFFIXES = {'.jpeg', '.jpg', '.png', '.svg', '.webp'}


def _determine_logo_label(
    raw_label: str | None,
    original_filename: str | None,
    fallback_filename: str,
) -> str:
    normalized = _normalize_label(raw_label)
    if normalized is not None:
        return normalized

    if original_filename:
        filename_stem = Path(original_filename).stem
        normalized_filename_stem = _normalize_label(filename_stem)
        if normalized_filename_stem is not None:
            return normalized_filename_stem

    return _label_from_filename(Path(fallback_filename).stem)


def _normalize_label(raw_label: str | None) -> str | None:
    if raw_label is None:
        return None

    normalized = ' '.join(raw_label.strip().split())
    if not normalized:
        return None

    return normalized[:120]


def _label_from_filename(filename_stem: str) -> str:
    compact = filename_stem.strip()
    if not compact:
        return 'Logo'

    if len(compact) >= 20 and all(
        character in '0123456789abcdef-' for character in compact.lower()
    ):
        return f'Logo {compact[:8]}'

    return compact.replace('_', ' ').replace('-', ' ')[:120]


def _get_tournament_logo_directory_path(party_id: PartyID) -> Path:
    return (
        get_current_byceps_app().byceps_config.data_path
        / 'parties'
        / party_id
        / 'netsession_tourney'
        / 'tournament_logos'
    )


def _to_tournament_logo_url_path(party_id: PartyID, filename: str) -> str:
    return f'/data/parties/{party_id}/netsession_tourney/tournament_logos/{filename}'


def _get_sponsor_logo_directory_path(party_id: PartyID) -> Path:
    return (
        get_current_byceps_app().byceps_config.data_path
        / 'parties'
        / party_id
        / 'netsession_tourney'
        / 'sponsor_logos'
    )


def _to_sponsor_logo_url_path(party_id: PartyID, filename: str) -> str:
    return (
        f'/data/parties/{party_id}/netsession_tourney/sponsor_logos/{filename}'
    )


def _get_discord_forum_image_directory_path(party_id: PartyID) -> Path:
    return (
        get_current_byceps_app().byceps_config.data_path
        / 'parties'
        / party_id
        / 'netsession_tourney'
        / 'discord_forum_images'
    )


def _to_discord_forum_image_url_path(party_id: PartyID, filename: str) -> str:
    return f'/data/parties/{party_id}/netsession_tourney/discord_forum_images/{filename}'
