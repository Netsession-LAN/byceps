"""
byceps.services.netsession_sponsor.logo_storage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sponsor logos live in the party's data directory
(`<data>/parties/<party_id>/sponsors/`), served by nginx at `/data/`.
Uploads get a new UUID file name; existing files are never overwritten.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from byceps.byceps_app import get_current_byceps_app
from byceps.services.party.models import PartyID
from byceps.util import upload
from byceps.util.image.image_type import ImageType, determine_image_type
from byceps.util.result import Err, Ok, Result
from byceps.util.uuid import generate_uuid7


ALLOWED_IMAGE_TYPES = frozenset(
    [ImageType.jpeg, ImageType.png, ImageType.svg, ImageType.webp]
)


def store_logo(party_id: PartyID, stream: BinaryIO) -> Result[str, str]:
    """Store the image, return its path relative to the data directory."""
    match determine_image_type(stream, ALLOWED_IMAGE_TYPES):
        case Ok(image_type):
            pass
        case Err(_):
            return Err('Nur JPEG, PNG, SVG oder WebP.')

    relative_path = (
        f'parties/{party_id}/sponsors/{generate_uuid7()}.{image_type.name}'
    )
    try:
        upload.store(
            stream,
            _data_path() / relative_path,
            create_parent_path_if_nonexistent=True,
        )
    except FileExistsError:
        return Err('Diese Logo-Datei gibt es bereits.')

    return Ok(relative_path)


def _data_path() -> Path:
    return get_current_byceps_app().byceps_config.data_path
