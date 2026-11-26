"""
:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from datetime import datetime

from byceps.services.external_accounts import external_accounts_service

from tests.helpers import generate_token


def test_find_connected_external_account_for_service_and_external_id(
    make_user,
):
    user = make_user()
    external_id = generate_token(12)

    external_accounts_service.connect_external_account(
        datetime.utcnow(),
        user.id,
        'example',
        external_id=external_id,
    ).unwrap()

    actual = external_accounts_service.find_connected_external_account_for_service_and_external_id(
        'example', external_id
    )
    assert actual is not None
    assert actual.user_id == user.id

    assert (
        external_accounts_service.find_connected_external_account_for_service_and_external_id(
            'other-service', external_id
        )
        is None
    )
    assert (
        external_accounts_service.find_connected_external_account_for_service_and_external_id(
            'example', generate_token(12)
        )
        is None
    )
