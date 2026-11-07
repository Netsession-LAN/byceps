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
    tournament_queries,
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

    monkeypatch.setattr(match_generation, 'auto_advance_byes', _boom)
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


def test_match_timeline_skips_tournament_events_before_the_match(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, stage = _create_se_tournament(
        party, admin_user, make_user, make_ticket_category, 2
    )
    match = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()[0]

    actions = [
        entry['action']
        for entry in match_queries.get_match_timeline_entries(
            party.id, tournament.id, match.id
        )
    ]

    assert 'tournament_published' not in actions


def test_regenerating_a_stage_with_results_is_refused(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, stage = _create_se_tournament(
        party, admin_user, make_user, make_ticket_category, 4
    )
    matches = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()
    first = next(m for m in matches if m.match_no == 1)
    assert result_service.report_result(
        party.id,
        tournament.id,
        first.id,
        admin_user.id,
        idempotency_key='regen',
        winner_slot=1,
        score={'display': '1:0', 'slots': {'1': 1, '2': 0}},
        actor_is_admin_or_referee=True,
    ).is_ok()

    again = match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )

    assert again.is_err()
    assert 'Ergebnis' in again.unwrap_err()
    assert double_grand_final.get_match_results({first.id}) != {}


def test_updating_a_stage_keeps_builder_settings_and_matches(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-stage-upd-' + generate_token().lower(),
        'NS Stage Update',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = stage_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'SE',
        {
            'include_consolation_final': False,
            'builder_kind': 'stage_builder_v1',
        },
        admin_user,
    ).unwrap()
    for _ in range(4):
        player = make_user('NS_StageUpd_' + generate_token())
        category = make_ticket_category(
            party.id, 'NS-Ticket-' + generate_token()
        )
        ticket = ticket_creation_service.create_ticket(category, player)
        ticket_user_management_service.appoint_user(ticket.id, player, player)
        registration_service.register_user(party.id, tournament.id, player)
    match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()

    # Renaming and timing: settings merged, matches kept.
    assert stage_service.update_stage(
        party.id,
        tournament.id,
        stage.id,
        StageType.single_elimination,
        'SE renamed',
        {
            'match_duration_minutes': 30,
            'result_report_mode': 'both_must_confirm',
        },
        admin_user,
    ).is_ok()
    updated = tournament_queries.get_stages_for_tournament(
        party.id, tournament.id
    )[0]
    assert updated.settings['builder_kind'] == 'stage_builder_v1'
    assert updated.settings['include_consolation_final'] is False
    assert updated.settings['match_duration_minutes'] == 30
    assert (
        len(match_queries.get_matches_for_tournament(party.id, tournament.id))
        == 3
    )

    # Changing the type: matches have to be generated again.
    assert stage_service.update_stage(
        party.id,
        tournament.id,
        stage.id,
        StageType.double_elimination,
        'DE',
        {'result_report_mode': 'both_must_confirm'},
        admin_user,
    ).is_ok()
    assert (
        match_queries.get_matches_for_tournament(party.id, tournament.id) == []
    )
