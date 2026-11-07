"""Optional check-in: only checked-in participants get into the bracket."""

from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from byceps.database import db
from byceps.services.netsession_tourney import (
    checkin_reminders,
    checkin_service,
    match_generation,
    match_queries,
    participant_admin_service,
    registration_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournament,
)
from byceps.services.netsession_tourney.models import (
    CheckinState,
    ParticipantStatus,
    RegistrationMode,
    StageType,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


def _tournament_with_players(
    party, admin_user, make_user, make_ticket_category, n
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-checkin-' + generate_token().lower(),
        'NS Checkin',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = stage_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'SE',
        {'include_consolation_final': False},
        admin_user,
    ).unwrap()
    players = []
    for _ in range(n):
        player = make_user('NS_Checkin_' + generate_token())
        category = make_ticket_category(
            party.id, 'NS-Ticket-' + generate_token()
        )
        ticket = ticket_creation_service.create_ticket(category, player)
        ticket_user_management_service.appoint_user(ticket.id, player, player)
        assert registration_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
        players.append(player)
    assert tournament_lifecycle_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    return tournament, stage, players


def _set_window(tournament_id, open_offset_min, close_offset_min):
    now = datetime.utcnow()
    db.session.execute(
        update(DbNetsessionTourneyTournament)
        .where(DbNetsessionTourneyTournament.id == tournament_id)
        .values(
            checkin_open_at=now + timedelta(minutes=open_offset_min),
            checkin_close_at=now + timedelta(minutes=close_offset_min),
        )
    )
    db.session.commit()


def test_only_checked_in_players_get_into_the_bracket(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, stage, players = _tournament_with_players(
        party, admin_user, make_user, make_ticket_category, 3
    )
    _set_window(tournament.id, -5, 10)

    for player in players[:2]:
        assert checkin_service.check_in(party.id, tournament.id, player).is_ok()

    # still open: no generation yet
    blocked = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert blocked.is_err()
    assert 'Check-in läuft noch' in blocked.unwrap_err()

    _set_window(tournament.id, -15, -1)
    assert checkin_service.check_in(
        party.id, tournament.id, players[2]
    ).is_err()

    matches = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()
    slots = match_queries.get_match_slots({m.id for m in matches})
    seated = {
        slot.participant_id
        for match_slots in slots.values()
        for slot in match_slots
        if slot.participant_id
    }
    assert len(seated) == 2


def test_check_in_needs_an_open_window_and_a_registration(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, _, players = _tournament_with_players(
        party, admin_user, make_user, make_ticket_category, 2
    )

    assert checkin_service.check_in(
        party.id, tournament.id, players[0]
    ).is_err()

    _set_window(tournament.id, 5, 30)
    assert checkin_service.check_in(
        party.id, tournament.id, players[0]
    ).is_err()

    _set_window(tournament.id, -5, 30)
    stranger = make_user('NS_Stranger_' + generate_token())
    assert checkin_service.check_in(party.id, tournament.id, stranger).is_err()
    assert checkin_service.check_in(party.id, tournament.id, players[0]).is_ok()


def test_admin_checks_in_by_hand_and_takes_it_back(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, _, players = _tournament_with_players(
        party, admin_user, make_user, make_ticket_category, 2
    )
    _set_window(tournament.id, -15, -1)  # already closed
    participant_id = db.session.scalar(
        select(DbNetsessionTourneyParticipant.id).filter_by(
            tournament_id=tournament.id, user_id=players[0].id
        )
    )

    checked_in = checkin_service.set_checkin_by_admin(
        party.id, tournament.id, participant_id, True, admin_user
    )
    assert checked_in.unwrap().checkin_state == CheckinState.checked_in

    revoked = checkin_service.set_checkin_by_admin(
        party.id, tournament.id, participant_id, False, admin_user
    )
    assert revoked.unwrap().checkin_state == CheckinState.pending


def test_checkin_reminder_is_sent_once_when_the_window_opens(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, _, players = _tournament_with_players(
        party, admin_user, make_user, make_ticket_category, 2
    )

    def reminders():
        return db.session.scalar(
            select(func.count())
            .select_from(DbNetsessionTourneyNotification)
            .filter_by(tournament_id=tournament.id, kind='checkin_open')
        )

    _set_window(tournament.id, 5, 30)  # not open yet
    checkin_reminders.send_due_checkin_reminders()
    assert reminders() == 0

    _set_window(tournament.id, -1, 30)
    checkin_reminders.send_due_checkin_reminders()
    assert reminders() == len(players)

    checkin_reminders.send_due_checkin_reminders()
    assert reminders() == len(players)


def test_admin_status_change_is_limited_to_safe_states(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, _, players = _tournament_with_players(
        party, admin_user, make_user, make_ticket_category, 2
    )
    participant_id = db.session.scalar(
        select(DbNetsessionTourneyParticipant.id).filter_by(
            tournament_id=tournament.id, user_id=players[0].id
        )
    )

    dropped = participant_admin_service.set_participant_status(
        party.id,
        tournament.id,
        participant_id,
        ParticipantStatus.dropped,
        admin_user,
    )
    assert dropped.is_err()
    assert 'entfernen' in dropped.unwrap_err().lower()

    assert participant_admin_service.set_participant_status(
        party.id,
        tournament.id,
        participant_id,
        ParticipantStatus.forming,
        admin_user,
    ).is_ok()
