"""
:Copyright: 2025-2026 Kevin Lehmann
:License: Revised BSD (see `LICENSE` file for details)
"""

from datetime import datetime

from byceps.services.external_accounts import external_accounts_service

from tests.helpers import generate_token


SERVICE = 'example'


def test_connect_external_account_already_connected(make_user):
    user = make_user()
    other_user = make_user()
    external_id = generate_token(12)

    first_result = connect(user, external_id)
    assert first_result.is_ok()

    second_result = connect(other_user, external_id)
    assert second_result.is_err()

    # The database session is still usable after the failed attempt.
    assert find_external_id(user) == external_id
    assert find_external_id(other_user) is None


def connect(user, external_id: str):
    return external_accounts_service.connect_external_account(
        datetime.utcnow(),
        user.id,
        SERVICE,
        external_id=external_id,
    )


def find_external_id(user) -> str | None:
    connected_external_account = external_accounts_service.find_connected_external_account_for_user_and_service(
        user.id, SERVICE
    )
    if connected_external_account is None:
        return None

    return connected_external_account.external_id
