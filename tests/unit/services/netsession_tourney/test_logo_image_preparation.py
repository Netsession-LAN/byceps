"""Logo uploads: size limit on width and height, readable errors."""

from io import BytesIO

from PIL import Image
import pytest

from byceps.services.netsession_tourney.logo_image_preparation import (
    prepare_logo_image,
    UNREADABLE_IMAGE_MESSAGE,
    UNSUPPORTED_IMAGE_MESSAGE,
)
from byceps.services.netsession_tourney.logo_service import ALLOWED_IMAGE_TYPES
from byceps.util.image.dimensions import Dimensions


MAX = Dimensions(1200, 300)


def _png(width: int, height: int) -> BytesIO:
    stream = BytesIO()
    Image.new('RGB', (width, height)).save(stream, format='PNG')
    stream.seek(0)
    return stream


@pytest.mark.parametrize(
    ('width', 'height'),
    [
        (600, 1200),  # narrow but too high (was missed once)
        (1300, 100),
    ],
)
def test_too_large_image_is_scaled_down(width, height):
    image_type, stream = prepare_logo_image(
        _png(width, height), ALLOWED_IMAGE_TYPES, MAX, force_square=False
    ).unwrap()
    with Image.open(stream) as image:
        assert image.width <= MAX.width
        assert image.height <= MAX.height
    assert image_type.name == 'png'


def test_image_within_limits_stays_as_is():
    original = _png(1200, 300)
    _, stream = prepare_logo_image(
        original, ALLOWED_IMAGE_TYPES, MAX, force_square=False
    ).unwrap()
    assert stream is original


def test_unsupported_file_gets_readable_message():
    result = prepare_logo_image(
        BytesIO(b'not an image at all'),
        ALLOWED_IMAGE_TYPES,
        MAX,
        force_square=False,
    )
    assert result.unwrap_err() == UNSUPPORTED_IMAGE_MESSAGE


def test_broken_image_gets_readable_message():
    data = _png(2000, 2000).getvalue()
    broken = BytesIO(data[:60])  # valid PNG header, cut off
    result = prepare_logo_image(
        broken, ALLOWED_IMAGE_TYPES, MAX, force_square=True
    )
    assert result.unwrap_err() == UNREADABLE_IMAGE_MESSAGE
