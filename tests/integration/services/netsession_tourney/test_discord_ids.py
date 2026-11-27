"""Discord IDs (snowflakes: 17-20 digits) are checked when configured, not
only later when sending fails."""

import pytest

from byceps.database import db
from byceps.services.netsession_tourney import (
    discord_dm_service,
    discord_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyDiscordDmConfig,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    TournamentMode,
)

from tests.helpers import generate_token


@pytest.mark.parametrize(
    ('channel_id', 'accepted'),
    [('123456789012345678', True), ('abc', False), ('12345', False)],
)
def test_forum_channel_id_must_be_a_discord_id(
    admin_app, party, admin_user, channel_id, accepted
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-discord-' + generate_token().lower(),
        'NS Discord',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()

    result = discord_service.configure_discord(
        party.id,
        tournament.id,
        admin_user,
        enabled=False,
        forum_channel_id=channel_id,
        discord_forum_image_url=None,
        applied_tag_ids=[],
        event_mask=[],
        discord_dm_enabled=False,
        discord_dm_event_mask=[],
    )

    assert result.is_ok() == accepted


@pytest.mark.parametrize(
    ('application_id', 'accepted'),
    [('123456789012345678', True), ('my-bot', False)],
)
def test_dm_application_id_must_be_a_discord_id(
    admin_app, party, application_id, accepted
):
    result = discord_dm_service.configure_discord_dm(
        party.id,
        enabled=False,
        application_id=application_id,
        bot_token=None,
        default_event_mask=[],
    )

    assert result.is_ok() == accepted


def test_rejected_dm_config_without_bot_token_is_not_stored(
    admin_app, make_party, brand
):
    """A new config without bot token used to stay in the database
    session after being rejected, so a later commit stored it."""
    party = make_party(brand)
    result = discord_dm_service.configure_discord_dm(
        party.id,
        enabled=True,
        application_id='123456789012345678',
        bot_token=None,
        default_event_mask=[],
    )
    assert result.is_err()

    db.session.commit()

    assert db.session.get(DbNetsessionTourneyDiscordDmConfig, party.id) is None
