"""One broken outbox row must not block the rows after it, and every
delivered row is stored right away (no double posts after a crash)."""

from datetime import datetime, timedelta

from byceps.database import db
from byceps.services.netsession_tourney import (
    discord_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyDiscordOutbox,
)
from byceps.services.netsession_tourney.models import (
    DiscordOutboxStatus,
    RegistrationMode,
    TournamentMode,
)
from byceps.util.uuid import generate_uuid7

from tests.helpers import generate_token


def test_unexpected_error_in_one_row_does_not_block_the_outbox(
    admin_app, party, admin_user, monkeypatch
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-outbox-' + generate_token().lower(),
        'NS Outbox',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    created_at = datetime.utcnow() - timedelta(minutes=5)
    broken_id, fine_id = generate_uuid7(), generate_uuid7()
    for row_id, event_name, offset in (
        (broken_id, 'broken', 0),
        (fine_id, 'fine', 1),
    ):
        db.session.add(
            DbNetsessionTourneyDiscordOutbox(
                row_id,
                tournament.id,
                event_name,
                {},
                created_at + timedelta(seconds=offset),
            )
        )
    db.session.commit()

    def deliver(db_row, credentials, credentials_error, now):
        if db_row.event_name == 'broken':
            raise RuntimeError('unexpected')
        db_row.status = DiscordOutboxStatus.sent.value

    monkeypatch.setattr(discord_service, '_deliver_discord_outbox_row', deliver)

    assert discord_service.process_discord_outbox(limit=50) >= 2
    db.session.rollback()

    db_broken = db.session.get(DbNetsessionTourneyDiscordOutbox, broken_id)
    db_fine = db.session.get(DbNetsessionTourneyDiscordOutbox, fine_id)
    assert db_broken.status == DiscordOutboxStatus.dead_letter.value
    assert 'RuntimeError' in db_broken.last_error
    assert db_fine.status == DiscordOutboxStatus.sent.value
