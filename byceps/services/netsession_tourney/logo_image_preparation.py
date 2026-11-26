"""
byceps.services.netsession_tourney.logo_image_preparation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Check an uploaded logo image and fit it into the maximum size, with
messages players understand (wrong format, unreadable file).
"""

from __future__ import annotations

from typing import BinaryIO

from PIL import Image

from byceps.util.image.dimensions import determine_dimensions, Dimensions
from byceps.util.image.image_type import determine_image_type, ImageType
from byceps.util.image.thumbnail import create_thumbnail
from byceps.util.result import Err, Ok, Result


UNSUPPORTED_IMAGE_MESSAGE = (
    'Dieses Dateiformat wird nicht unterstützt. Erlaubt sind: JPEG, PNG, WEBP.'
)
UNREADABLE_IMAGE_MESSAGE = (
    'Das Bild konnte nicht gelesen werden. Bitte speichere es als JPEG, PNG '
    'oder WEBP neu und versuche es nochmal.'
)


def prepare_logo_image(
    stream: BinaryIO,
    allowed_types: frozenset[ImageType],
    max_dimensions: Dimensions,
    *,
    force_square: bool,
) -> Result[tuple[ImageType, BinaryIO], str]:
    """Return the image type and the (possibly scaled down) image."""
    match determine_image_type(stream, allowed_types):
        case Ok(image_type):
            pass
        case Err(_):
            return Err(UNSUPPORTED_IMAGE_MESSAGE)

    if image_type == ImageType.svg:
        return Ok((image_type, stream))

    try:
        stream = _fit_logo_image(
            stream, image_type, max_dimensions, force_square=force_square
        )
    except OSError, ValueError, Image.DecompressionBombError:
        return Err(UNREADABLE_IMAGE_MESSAGE)

    return Ok((image_type, stream))


def _fit_logo_image(
    stream: BinaryIO,
    image_type: ImageType,
    max_dimensions: Dimensions,
    *,
    force_square: bool,
) -> BinaryIO:
    """Return the image, scaled down (or squared) if necessary."""
    dimensions = determine_dimensions(stream)
    if not _needs_logo_image_thumbnail(
        dimensions, max_dimensions, force_square=force_square
    ):
        return stream

    return create_thumbnail(
        stream,
        image_type.name,
        max_dimensions,
        force_square=force_square,
    )


def _needs_logo_image_thumbnail(
    dimensions: Dimensions,
    max_dimensions: Dimensions,
    *,
    force_square: bool,
) -> bool:
    too_large = (
        dimensions.width > max_dimensions.width
        or dimensions.height > max_dimensions.height
    )
    return too_large or (force_square and not dimensions.is_square)
