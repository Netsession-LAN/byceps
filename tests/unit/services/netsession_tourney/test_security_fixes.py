"""Netsession: security fixes from the tournament QA run (2026-11-04)."""

import pytest

from byceps.services.netsession_tourney.blueprints.site.body_rendering import (
    render_formatted_body_html,
)
from byceps.services.netsession_tourney.browser_push_endpoint import (
    is_allowed_push_endpoint,
    validate_push_subscription,
)
from byceps.services.netsession_tourney.logo_service import (
    ALLOWED_IMAGE_TYPES,
    _exceeds,
)
from byceps.services.netsession_tourney.models import RuleTemplateBodyFormat
from byceps.services.netsession_tourney.sponsor_link import normalize_target_url
from byceps.util.image.dimensions import Dimensions
from byceps.util.image.image_type import ImageType


@pytest.mark.parametrize('body_format', list(RuleTemplateBodyFormat))
@pytest.mark.parametrize(
    'payload',
    [
        '<script>alert(1)</script>',
        '<img src="x" onerror="alert(1)">',
        '<a href="javascript:alert(1)">x</a>',
    ],
)
def test_rule_and_prize_texts_are_sanitized(body_format, payload):
    html = str(render_formatted_body_html(f'Hallo {payload}', body_format))

    assert '<script' not in html
    assert 'onerror' not in html
    assert 'javascript:' not in html


def test_rule_texts_keep_harmless_markup():
    html = str(
        render_formatted_body_html(
            '# Regeln\n\n- **fair** spielen', RuleTemplateBodyFormat.markdown
        )
    )

    assert '<h1>Regeln</h1>' in html
    assert '<strong>fair</strong>' in html


@pytest.mark.parametrize(
    'endpoint',
    [
        'https://fcm.googleapis.com/fcm/send/abc',
        'https://updates.push.services.mozilla.com/wpush/v2/abc',
        'https://web.push.apple.com/abc',
        'https://db5p.notify.windows.com/w/?token=abc',
    ],
)
def test_known_push_services_are_allowed(endpoint):
    assert is_allowed_push_endpoint(endpoint)


@pytest.mark.parametrize(
    'endpoint',
    [
        'javascript:alert(1)',
        'http://fcm.googleapis.com/fcm/send/abc',
        'https://db:5432/',
        'https://127.0.0.1/x',
        'https://evil.example/fcm.googleapis.com',
        'https://fcm.googleapis.com.evil.example/x',
        'https://fcm.googleapis.com:8443/x',
    ],
)
def test_other_push_endpoints_are_rejected(endpoint):
    assert not is_allowed_push_endpoint(endpoint)
    assert validate_push_subscription(endpoint, 'key', 'auth') is not None


def test_incomplete_push_subscription_is_rejected():
    assert validate_push_subscription('', 'key', 'auth') is not None


def test_svg_uploads_are_not_allowed():
    assert ImageType.svg not in ALLOWED_IMAGE_TYPES


@pytest.mark.parametrize(
    ('size', 'expected'),
    [
        (Dimensions(600, 1200), True),  # narrow but too high (was missed)
        (Dimensions(1300, 100), True),
        (Dimensions(1200, 300), False),
    ],
)
def test_image_size_limit_checks_width_and_height(size, expected):
    assert _exceeds(size, Dimensions(1200, 300)) is expected


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('javascript:alert(1)', None),
        ('JavaScript:alert(1)', None),
        ('data:text/html,x', None),
        ('example.org', 'https://example.org'),
        ('https://www.noctua.at', 'https://www.noctua.at'),
        ('  ', None),
        (None, None),
    ],
)
def test_sponsor_target_url_is_normalized(value, expected):
    assert normalize_target_url(value) == expected
