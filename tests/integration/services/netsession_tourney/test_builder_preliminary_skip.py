"""A builder preliminary is skipped when everybody fits into the main
stage: the main stage is generated directly from the ready participants."""

from types import SimpleNamespace

from flask import g

from byceps.services.netsession_tourney import (
    match_generation,
    registration_service,
    stage_builder_service,
    tournament_queries,
    tournament_service,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_helpers import (
    get_stage_generation_block_reason,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    StageType,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


def _builder_tournament(party, admin_user, make_user, make_ticket_category, n):
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-builder-skip-' + generate_token().lower(),
        'NS Builder Skip',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        participant_limit=64,
    ).unwrap()
    assert stage_builder_service.build_stage_builder_plan(
        party.id,
        tournament.id,
        generation_basis='ready',
        main_stage_type=StageType.single_elimination,
        main_stage_size=8,
        max_players_per_match=None,
        preliminary_type=StageType.round_robin_groups,
        round_robin_builder_mode='standard',
        round_robin_group_count=None,
        swiss_threshold=None,
        match_duration_minutes=None,
        max_matches_per_round=None,
        break_between_rounds_minutes=None,
        initiator=admin_user,
    ).is_ok()
    for _ in range(n):
        player = make_user('NS_Skip_' + generate_token())
        category = make_ticket_category(
            party.id, 'NS-Ticket-' + generate_token()
        )
        ticket = ticket_creation_service.create_ticket(category, player)
        ticket_user_management_service.appoint_user(ticket.id, player, player)
        assert registration_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
    stages = tournament_queries.get_stages_for_tournament(
        party.id, tournament.id
    )
    main = next(s for s in stages if s.settings.get('builder_role') == 'main')
    return tournament, stages, main


def test_main_stage_is_not_blocked_by_an_unneeded_preliminary(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament, stages, main = _builder_tournament(
        party, admin_user, make_user, make_ticket_category, 6
    )

    reason = _block_reason(main, stages)

    assert reason is None
    matches = match_generation.generate_stage_matches(
        party.id, tournament.id, main.id, admin_user
    ).unwrap()
    assert matches


def test_main_stage_waits_for_a_needed_preliminary(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    _, stages, main = _builder_tournament(
        party, admin_user, make_user, make_ticket_category, 10
    )

    reason = _block_reason(main, stages)

    assert reason is not None


def _block_reason(main, stages):
    g.user = SimpleNamespace(locale=None)  # gettext outside a request
    return get_stage_generation_block_reason(
        main, {s.id: s for s in stages}, {}
    )
