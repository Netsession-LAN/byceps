"""A result report and a match generation are one transaction each: when
something fails half-way, nothing of it may be stored."""

from datetime import datetime, timedelta

import pytest

from byceps.database import db
from byceps.services.netsession_tourney import (
    double_grand_final,
    match_advancement,
    match_generation,
    match_queries,
    registration_service,
    result_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_service,
)
from byceps.services.netsession_tourney.dbmodels import DbNetsessionTourneyMatch
from byceps.services.netsession_tourney.models import (
    MatchState,
    RegistrationMode,
    StageType,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


class _Boom(Exception):
    pass


def _boom(*args, **kwargs):
    raise _Boom()


def _create_se_tournament(
    party, admin_user, make_user, make_ticket_category, n
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-tx-' + generate_token().lower(),
        'NS TX',
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
    for _ in range(n):
        player = make_user('NS_TX_' + generate_token())
        category = make_ticket_category(
            party.id, 'NS-Ticket-' + generate_token()
        )
        ticket = ticket_creation_service.create_ticket(category, player)
        ticket_user_management_service.appoint_user(ticket.id, player, player)
        assert registration_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
    assert tournament_lifecycle_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    return tournament, stage


def test_failing_advancement_stores_no_part_of_the_result(
    admin_app, party, admin_user, make_user, make_ticket_category, monkeypatch
):
    tournament, stage = _create_se_tournament(
        party, admin_user, make_user, make_ticket_category, 4
    )
    match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()
    match1 = next(
        m
        for m in match_queries.get_matches_for_tournament(
            party.id, tournament.id
        )
        if m.match_no == 1
    )

    monkeypatch.setattr(
        match_advancement,
        '_enqueue_notifications_for_still_ready_matches',
        _boom,
    )
    with pytest.raises(_Boom):
        result_service.report_result(
            party.id,
            tournament.id,
            match1.id,
            admin_user.id,
            idempotency_key='tx',
            winner_slot=1,
            score={'display': '1:0', 'slots': {'1': 1, '2': 0}},
            actor_is_admin_or_referee=True,
        )
    db.session.rollback()

    db_match1 = db.session.get(DbNetsessionTourneyMatch, match1.id)
    assert db_match1.state == MatchState.ready.value
    assert double_grand_final.get_match_results({match1.id}) == {}


def test_failing_generation_stores_no_matches(
    admin_app, party, admin_user, make_user, make_ticket_category, monkeypatch
):
    tournament, stage = _create_se_tournament(
        party, admin_user, make_user, make_ticket_category, 3
    )

    monkeypatch.setattr(match_generation, '_auto_advance_byes', _boom)
    with pytest.raises(_Boom):
        match_generation.generate_stage_matches(
            party.id, tournament.id, stage.id, admin_user
        )
    db.session.rollback()

    assert (
        match_queries.get_matches_for_tournament(party.id, tournament.id) == []
    )


def test_unconfirmed_result_goes_to_admin_review_after_deadline(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, stage = _create_se_tournament(
        party, admin_user, make_user, make_ticket_category, 2
    )
    match = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()[0]
    db_match = db.session.get(DbNetsessionTourneyMatch, match.id)
    db_match.state = MatchState.pending_confirmation.value
    db_match.confirmation_deadline_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()

    assert match_advancement.resolve_pending_confirmations() >= 1

    db.session.expire_all()
    db_match = db.session.get(DbNetsessionTourneyMatch, match.id)
    assert db_match.state == MatchState.needs_admin_review.value
    assert db_match.confirmation_deadline_at is None
