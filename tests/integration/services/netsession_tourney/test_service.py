from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from byceps.database import db
from byceps.services.netsession_tourney.dbmodels import (
    DbNetsessionTourneyBrowserPushOutbox,
    DbNetsessionTourneyDiscordDmOutbox,
    DbNetsessionTourneyMatch,
    DbNetsessionTourneyMatchResult,
    DbNetsessionTourneyMatchSlot,
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyParticipant,
    DbNetsessionTourneyTournamentAdmin,
    DbNetsessionTourneyTournamentPrize,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)
from tests.helpers import generate_token

from byceps.services.netsession_tourney.models import (
    CoinChargeMode,
    MatchState,
    ParticipantStatus,
    RegistrationMode,
    RuleTemplateBodyFormat,
    StageStatus,
    StageType,
    TournamentMode,
    TournamentStatus,
)
from byceps.services.netsession_tourney import service as tourney_service


@pytest.fixture
def isolated_party(make_party, brand):
    """A party of its own, as the session-wide `party` fixture accumulates
    tournament categories from other tests."""
    return make_party(brand)


def test_duel_happy_path_with_idempotent_result_report(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_Challenger_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-duel-' + generate_token().lower(),
        'NS Duel Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main Bracket',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )

    # Players may only report results while the tournament is live.
    publish_result = tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    )
    assert publish_result.is_ok()

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()
    matches = generation_result.unwrap()
    assert matches
    match = matches[0]

    report1 = tourney_service.report_result(
        party.id,
        tournament.id,
        match.id,
        user.id,
        idempotency_key='idem-key-1',
        winner_slot=1,
        score={'map1': '1:0'},
    )
    assert report1.is_ok()
    result1 = report1.unwrap()

    report2 = tourney_service.report_result(
        party.id,
        tournament.id,
        match.id,
        user.id,
        idempotency_key='idem-key-1',
        winner_slot=1,
        score={'map1': '1:0'},
    )
    assert report2.is_ok()
    result2 = report2.unwrap()

    assert result1.id == result2.id


def test_tournament_categories_can_be_created_and_reordered(
    admin_app, isolated_party
):
    party = isolated_party
    create_main_result = tourney_service.create_tournament_category(
        party.id, 'Hauptturnier'
    )
    assert create_main_result.is_ok()
    main_category = create_main_result.unwrap()

    create_side_result = tourney_service.create_tournament_category(
        party.id, 'Nebenturnier'
    )
    assert create_side_result.is_ok()
    side_category = create_side_result.unwrap()

    categories = tourney_service.get_tournament_categories_for_party(party.id)
    assert [category.title for category in categories] == [
        'Hauptturnier',
        'Nebenturnier',
    ]

    move_up_result = tourney_service.move_tournament_category_up(main_category.id)
    assert move_up_result.is_err()

    move_down_result = tourney_service.move_tournament_category_down(
        main_category.id
    )
    assert move_down_result.is_ok()

    categories = tourney_service.get_tournament_categories_for_party(party.id)
    assert [category.title for category in categories] == [
        'Nebenturnier',
        'Hauptturnier',
    ]

    move_down_result = tourney_service.move_tournament_category_down(
        side_category.id
    )
    assert move_down_result.is_ok()

    categories = tourney_service.get_tournament_categories_for_party(party.id)
    assert [category.title for category in categories] == [
        'Hauptturnier',
        'Nebenturnier',
    ]


def test_tournament_rule_templates_can_be_created_and_updated(
    admin_app, party
):
    create_result = tourney_service.create_tournament_rule_template(
        party.id,
        'pubg-regeln',
        'PubG Regeln',
        RuleTemplateBodyFormat.markdown,
        '# Regeln\n\nKeine Cheats.',
    )
    assert create_result.is_ok()
    created_template = create_result.unwrap()
    assert created_template.slug == 'pubg-regeln'
    assert created_template.body_format == RuleTemplateBodyFormat.markdown

    templates = tourney_service.get_tournament_rule_templates_for_party(
        party.id
    )
    assert [template.slug for template in templates] == ['pubg-regeln']

    update_result = tourney_service.update_tournament_rule_template(
        created_template.id,
        'pubg-rules',
        'PubG Rules',
        RuleTemplateBodyFormat.html,
        '<h2>Rules</h2><p>No cheats.</p>',
    )
    assert update_result.is_ok()
    updated_template = update_result.unwrap()
    assert updated_template.slug == 'pubg-rules'
    assert updated_template.body_format == RuleTemplateBodyFormat.html

    found_template = (
        tourney_service.find_tournament_rule_template_by_slug_for_party(
            party.id, 'pubg-rules'
        )
    )
    assert found_template is not None
    assert found_template.id == created_template.id


def test_tournaments_are_sorted_by_category_position(
    admin_app, isolated_party, admin_user
):
    party = isolated_party
    main_category_result = tourney_service.create_tournament_category(
        party.id, 'Hauptturnier'
    )
    assert main_category_result.is_ok()
    main_category = main_category_result.unwrap()

    side_category_result = tourney_service.create_tournament_category(
        party.id, 'Nebenturnier'
    )
    assert side_category_result.is_ok()
    side_category = side_category_result.unwrap()

    side_tourney_result = tourney_service.create_tournament(
        party.id,
        'ns-side-' + generate_token().lower(),
        'Side Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        category_id=side_category.id,
    )
    assert side_tourney_result.is_ok()

    main_tourney_result = tourney_service.create_tournament(
        party.id,
        'ns-main-' + generate_token().lower(),
        'Main Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        category_id=main_category.id,
    )
    assert main_tourney_result.is_ok()

    tournaments = tourney_service.get_tournaments_for_party(party.id)
    assert [tournament.title for tournament in tournaments] == [
        'Main Cup',
        'Side Cup',
    ]


def test_ffa_requires_admin_to_finalize_results(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_FFA_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-ffa-' + generate_token().lower(),
        'NS FFA Demo',
        TournamentMode.ffa,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.ffa_simple,
        'FFA Stage',
        {'max_players_per_match': 8},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()
    match = generation_result.unwrap()[0]

    user_report = tourney_service.report_result(
        party.id,
        tournament.id,
        match.id,
        user.id,
        idempotency_key='ffa-user-key',
        winner_slot=1,
    )
    assert user_report.is_err()

    admin_report = tourney_service.report_result(
        party.id,
        tournament.id,
        match.id,
        admin_user.id,
        idempotency_key='ffa-admin-key',
        winner_slot=1,
        actor_is_admin_or_referee=True,
        admin_comment='Finalized by referee.',
    )
    assert admin_report.is_ok()


def test_admin_match_operations_and_participant_disqualification(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_AdminOps_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-admin-' + generate_token().lower(),
        'NS Admin Ops Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main Bracket',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()
    match = generation_result.unwrap()[0]

    reschedule_result = tourney_service.reschedule_match(
        party.id,
        tournament.id,
        match.id,
        tournament.starts_at or datetime.utcnow(),
        admin_user,
        comment='Schedule update',
    )
    assert reschedule_result.is_ok()

    dispute_result = tourney_service.open_match_dispute(
        party.id,
        tournament.id,
        match.id,
        admin_user,
        reason_code='rule_violation',
        comment='Need admin review.',
    )
    assert dispute_result.is_ok()

    walkover_result = tourney_service.apply_walkover_result(
        party.id,
        tournament.id,
        match.id,
        admin_user,
        winner_slot=1,
        idempotency_key='walkover-key-1',
        comment='No-show after grace period.',
    )
    assert walkover_result.is_ok()

    participants = tourney_service.get_participants_for_tournament(
        party.id, tournament.id
    )
    target = next(p for p in participants if p.user_id == challenger.id)

    dq_result = tourney_service.disqualify_participant(
        party.id,
        tournament.id,
        target.id,
        admin_user,
        reason_code='cheating',
        comment='Confirmed violation.',
    )
    assert dq_result.is_ok()
    assert dq_result.unwrap().status == ParticipantStatus.dropped


def test_single_elimination_with_5_participants_handles_byes_fairly(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    participants = [
        user,
        make_user('NS_Bye_A_' + generate_token()),
        make_user('NS_Bye_B_' + generate_token()),
        make_user('NS_Bye_C_' + generate_token()),
        make_user('NS_Bye_D_' + generate_token()),
    ]

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-bye-' + generate_token().lower(),
        'NS Bye Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main Bracket',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert (
            tourney_service.register_user(
                party.id, tournament.id, participant
            ).is_ok()
        )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    assert matches
    slots_by_match_id = tourney_service.get_match_slots(
        {match.id for match in matches}
    )

    round1_matches = [match for match in matches if match.round_no == 1]
    assert len(round1_matches) == 4
    assert all(
        any(slot.participant_id is not None for slot in slots_by_match_id[match.id])
        for match in round1_matches
    )

    final_round_no = max(match.round_no for match in matches)
    final_round_matches = [
        match for match in matches if match.round_no == final_round_no
    ]
    assert len(final_round_matches) == 2
    main_final_matches = []
    for match in final_round_matches:
        slots = slots_by_match_id[match.id]
        has_loser_feed = any(
            slot.source_outcome.value == 'loser'
            for slot in slots
            if slot.source_match_slot_id is not None
        )
        if not has_loser_feed:
            main_final_matches.append(match)
    assert len(main_final_matches) == 1
    final_slots = slots_by_match_id[main_final_matches[0].id]
    assert all(slot.participant_id is None for slot in final_slots)


def test_double_elimination_generation_creates_wb_and_lb_paths(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    participants = [
        user,
        make_user('NS_DE_A_' + generate_token()),
        make_user('NS_DE_B_' + generate_token()),
        make_user('NS_DE_C_' + generate_token()),
        make_user('NS_DE_D_' + generate_token()),
        make_user('NS_DE_E_' + generate_token()),
        make_user('NS_DE_F_' + generate_token()),
        make_user('NS_DE_G_' + generate_token()),
    ]

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-de-' + generate_token().lower(),
        'NS Double Elim Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.double_elimination,
        'Double Elimination',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert (
            tourney_service.register_user(
                party.id, tournament.id, participant
            ).is_ok()
        )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    slots_by_match_id = tourney_service.get_match_slots(
        {match.id for match in matches}
    )
    assert matches
    assert any(
        slot.source_outcome.value == 'loser'
        for slots in slots_by_match_id.values()
        for slot in slots
        if slot.source_match_slot_id is not None
    )
    max_round_no = max(match.round_no for match in matches)
    assert len([match for match in matches if match.round_no == max_round_no]) == 1


def test_double_elimination_with_5_participants_propagates_loser_bye_paths(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    participants = [
        user,
        make_user('NS_DE5_A_' + generate_token()),
        make_user('NS_DE5_B_' + generate_token()),
        make_user('NS_DE5_C_' + generate_token()),
        make_user('NS_DE5_D_' + generate_token()),
    ]

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-de5-' + generate_token().lower(),
        'NS Double Elim 5 Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.double_elimination,
        'Double Elimination',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert tourney_service.register_user(
            party.id, tournament.id, participant
        ).is_ok()

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    match_ids = {match.id for match in matches}

    # LB branches that are fed only by byes should auto-complete as empty
    # matches so their downstream path is no longer blocked.
    db_results = db.session.scalars(
        select(DbNetsessionTourneyMatchResult).filter(
            DbNetsessionTourneyMatchResult.match_id.in_(match_ids)
        )
    ).all()
    empty_match_ids = {
        result.match_id
        for result in db_results
        if result.winner_slot is None and result.score_json.get('empty_match') is True
    }
    assert empty_match_ids

    completed_match_ids = {
        db_match.id
        for db_match in db.session.scalars(
            select(DbNetsessionTourneyMatch).filter(
                DbNetsessionTourneyMatch.id.in_(empty_match_ids)
            )
        ).all()
        if db_match.state == 'completed'
    }
    assert completed_match_ids == empty_match_ids

    db_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot).filter(
            DbNetsessionTourneyMatchSlot.match_id.in_(match_ids)
        )
    ).all()
    source_match_id_by_slot_id = {
        db_slot.id: db_slot.match_id for db_slot in db_slots
    }
    downstream_slots_from_empty_matches = [
        db_slot
        for db_slot in db_slots
        if db_slot.source_match_slot_id is not None
        and source_match_id_by_slot_id.get(db_slot.source_match_slot_id)
        in empty_match_ids
    ]
    assert downstream_slots_from_empty_matches
    assert all(
        db_slot.participant_id is None
        for db_slot in downstream_slots_from_empty_matches
    )


def test_double_elimination_advances_loser_path_after_wb_result_with_bye(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    participants = [
        user,
        make_user('NS_DE5R_A_' + generate_token()),
        make_user('NS_DE5R_B_' + generate_token()),
        make_user('NS_DE5R_C_' + generate_token()),
        make_user('NS_DE5R_D_' + generate_token()),
    ]

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-de5r-' + generate_token().lower(),
        'NS Double Elim 5 Report Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.double_elimination,
        'Double Elimination',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert tourney_service.register_user(
            party.id, tournament.id, participant
        ).is_ok()

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    round1_matches = sorted(
        [match for match in matches if match.round_no == 1],
        key=lambda match: match.match_no,
    )
    assert round1_matches

    slots_by_match_id = tourney_service.get_match_slots(
        {match.id for match in matches}
    )
    wb_match = next(
        (
            match
            for match in round1_matches
            if len(
                [
                    slot
                    for slot in slots_by_match_id[match.id]
                    if slot.participant_id is not None
                ]
            )
            == 2
        ),
        None,
    )
    assert wb_match is not None
    wb_slots = slots_by_match_id[wb_match.id]
    winner_slot = wb_slots[0].slot_no
    winner_participant_id = wb_slots[0].participant_id
    loser_participant_id = wb_slots[1].participant_id
    assert winner_participant_id is not None
    assert loser_participant_id is not None

    db_source_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            match_id=wb_match.id, slot_no=1
        )
    )
    assert db_source_slot is not None

    db_loser_slot = db.session.scalar(
        select(DbNetsessionTourneyMatchSlot).filter_by(
            source_match_slot_id=db_source_slot.id,
            source_outcome='loser',
        )
    )
    assert db_loser_slot is not None

    lb_match_id = db_loser_slot.match_id

    report_result = tourney_service.report_result(
        party.id,
        tournament.id,
        wb_match.id,
        admin_user.id,
        idempotency_key='de-bye-report-' + generate_token(),
        winner_slot=winner_slot,
        score={'display': '1:0'},
        actor_is_admin_or_referee=True,
        admin_comment='Auto test',
    )
    assert report_result.is_ok()

    db_lb_match = db.session.get(DbNetsessionTourneyMatch, lb_match_id)
    assert db_lb_match is not None
    assert db_lb_match.state == 'completed'

    db_lb_slots = db.session.scalars(
        select(DbNetsessionTourneyMatchSlot)
        .filter_by(match_id=lb_match_id)
        .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
    ).all()
    lb_filled_slots = [
        db_slot for db_slot in db_lb_slots if db_slot.participant_id is not None
    ]
    assert len(lb_filled_slots) == 1
    assert lb_filled_slots[0].participant_id == loser_participant_id

    db_lb_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=lb_match_id)
    )
    assert db_lb_result is not None
    assert db_lb_result.winner_slot == lb_filled_slots[0].slot_no


def test_double_elimination_with_double_grand_final_skips_reset_match_if_not_needed(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    participants = [
        user,
        make_user('NS_DEDG_A_' + generate_token()),
        make_user('NS_DEDG_B_' + generate_token()),
        make_user('NS_DEDG_C_' + generate_token()),
        make_user('NS_DEDG_D_' + generate_token()),
        make_user('NS_DEDG_E_' + generate_token()),
        make_user('NS_DEDG_F_' + generate_token()),
        make_user('NS_DEDG_G_' + generate_token()),
    ]

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-dedg-' + generate_token().lower(),
        'NS Double Elim + Double GF',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.double_elimination_double_grand_final,
        'Double Elimination + Double GF',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert tourney_service.register_user(
            party.id, tournament.id, participant
        ).is_ok()

    publish_result = tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    )
    assert publish_result.is_ok()

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    slots_by_match_id = tourney_service.get_match_slots({match.id for match in matches})
    source_match_id_by_slot_id = {
        slot.id: slot.match_id
        for slots in slots_by_match_id.values()
        for slot in slots
    }

    grand_final_2 = None
    grand_final_1 = None
    for match in matches:
        slots = slots_by_match_id.get(match.id, [])
        if len(slots) < 2:
            continue
        if any(slot.source_match_slot_id is None for slot in slots):
            continue
        source_slot_ids = {slot.source_match_slot_id for slot in slots}
        outcomes = {slot.source_outcome.value for slot in slots}
        if len(source_slot_ids) == 1 and outcomes == {'winner', 'loser'}:
            grand_final_2 = match
            source_slot_id = next(iter(source_slot_ids))
            source_match_id = source_match_id_by_slot_id[source_slot_id]
            grand_final_1 = next(
                current_match
                for current_match in matches
                if current_match.id == source_match_id
            )
            break

    assert grand_final_1 is not None
    assert grand_final_2 is not None

    # Play the bracket up to the grand final, so that grand final #1 has its
    # actual participants (winner bracket side in slot 1).
    _complete_ready_matches(
        party.id,
        tournament.id,
        admin_user,
        excluded_match_ids={grand_final_1.id, grand_final_2.id},
    )
    db_grand_final_1 = db.session.get(DbNetsessionTourneyMatch, grand_final_1.id)
    assert db_grand_final_1.state == 'ready'

    report_result = tourney_service.report_result(
        party.id,
        tournament.id,
        grand_final_1.id,
        admin_user.id,
        idempotency_key='de-double-gf-1-' + generate_token(),
        winner_slot=1,
        score={'display': '2:0'},
        actor_is_admin_or_referee=True,
        admin_comment='GF #1 winner is WB side',
    )
    assert report_result.is_ok()

    db_grand_final_2 = db.session.get(DbNetsessionTourneyMatch, grand_final_2.id)
    assert db_grand_final_2 is not None
    assert db_grand_final_2.state == 'completed'

    db_grand_final_2_result = db.session.scalar(
        select(DbNetsessionTourneyMatchResult).filter_by(match_id=grand_final_2.id)
    )
    assert db_grand_final_2_result is not None
    assert db_grand_final_2_result.winner_slot is None
    assert (
        db_grand_final_2_result.score_json.get('grand_final_reset_skipped') is True
    )

    blocked_report_result = tourney_service.report_result(
        party.id,
        tournament.id,
        grand_final_2.id,
        admin_user.id,
        idempotency_key='de-double-gf-2-' + generate_token(),
        winner_slot=1,
        score={'display': '2:1'},
        actor_is_admin_or_referee=True,
        admin_comment='Should be blocked',
    )
    assert blocked_report_result.is_err()
    assert 'canceled' in blocked_report_result.unwrap_err().lower()


def test_registration_limit_and_deregistration(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_Limit_A_' + generate_token())
    reserve = make_user('NS_Limit_B_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-limit-' + generate_token().lower(),
        'NS Limit Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        participant_limit=2,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )
    _assign_party_ticket_to_user(party.id, reserve, make_ticket_category)

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )
    assert tourney_service.register_user(party.id, tournament.id, reserve).is_err()

    assert tourney_service.deregister_user(party.id, tournament.id, user).is_ok()
    assert tourney_service.register_user(party.id, tournament.id, reserve).is_ok()

    visible_participants = tourney_service.get_participants_for_tournament(
        party.id, tournament.id
    )
    assert all(participant.user_id != user.id for participant in visible_participants)

    all_participants = tourney_service.get_participants_for_tournament(
        party.id, tournament.id, include_dropped=True
    )
    dropped_participant = next(
        participant
        for participant in all_participants
        if participant.user_id == user.id
    )
    assert dropped_participant.status == ParticipantStatus.dropped


def test_admin_can_remove_participant(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_Remove_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-remove-' + generate_token().lower(),
        'NS Remove Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )

    participants = tourney_service.get_participants_for_tournament(
        party.id, tournament.id
    )
    challenger_participant = next(
        participant
        for participant in participants
        if participant.user_id == challenger.id
    )

    remove_result = tourney_service.remove_participant_by_admin(
        party.id,
        tournament.id,
        challenger_participant.id,
        admin_user,
        comment='Removed by admin.',
    )
    assert remove_result.is_ok()
    assert remove_result.unwrap().status == ParticipantStatus.dropped

    visible_participants_after_remove = tourney_service.get_participants_for_tournament(
        party.id, tournament.id
    )
    assert all(
        participant.id != challenger_participant.id
        for participant in visible_participants_after_remove
    )


def test_admin_can_add_user_participant_for_solo_tournament(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    candidate = make_user('NS_AdminAdd_' + generate_token())
    for ticket_user in [candidate]:
        _assign_party_ticket_to_user(party.id, ticket_user, make_ticket_category)

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-admin-add-' + generate_token().lower(),
        'NS Admin Add User',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    add_result = tourney_service.add_user_participant_by_admin(
        party.id,
        tournament.id,
        candidate,
        admin_user,
    )
    assert add_result.is_ok()
    participant = add_result.unwrap()
    assert participant.user_id == candidate.id

    participants = tourney_service.get_participants_for_tournament(
        party.id, tournament.id
    )
    assert any(item.user_id == candidate.id for item in participants)


def test_admin_can_create_team_and_manage_team_members(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    captain = make_user('NS_AdminCaptain_' + generate_token())
    member = make_user('NS_AdminMember_' + generate_token())
    for ticket_user in [captain, member]:
        _assign_party_ticket_to_user(party.id, ticket_user, make_ticket_category)

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-admin-team-' + generate_token().lower(),
        'NS Admin Team Management',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=5,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    create_team_result = tourney_service.create_team_by_admin(
        party.id,
        tournament.id,
        'Team Admin',
        captain,
        admin_user,
    )
    assert create_team_result.is_ok()
    team_participant = create_team_result.unwrap()

    add_member_result = tourney_service.add_team_member_by_admin(
        party.id,
        tournament.id,
        team_participant.id,
        member,
        admin_user,
    )
    assert add_member_result.is_ok()

    members_after_add = tourney_service.get_team_members_for_participants(
        {team_participant.id}
    )
    member_user_ids_after_add = {
        team_member.user_id
        for team_member in members_after_add.get(team_participant.id, [])
    }
    assert member_user_ids_after_add == {captain.id, member.id}

    remove_member_result = tourney_service.remove_team_member_by_admin(
        party.id,
        tournament.id,
        team_participant.id,
        member.id,
        admin_user,
    )
    assert remove_member_result.is_ok()

    members_after_remove = tourney_service.get_team_members_for_participants(
        {team_participant.id}
    )
    member_user_ids_after_remove = {
        team_member.user_id
        for team_member in members_after_remove.get(team_participant.id, [])
    }
    assert member_user_ids_after_remove == {captain.id}


def test_admin_can_reassign_team_captain(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    captain = make_user('NS_AdminCaptainA_' + generate_token())
    new_captain = make_user('NS_AdminCaptainB_' + generate_token())
    for ticket_user in [captain, new_captain]:
        _assign_party_ticket_to_user(party.id, ticket_user, make_ticket_category)

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-admin-captain-' + generate_token().lower(),
        'NS Admin Captain Reassign',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=5,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    create_team_result = tourney_service.create_team_by_admin(
        party.id,
        tournament.id,
        'Team Captain Test',
        captain,
        admin_user,
    )
    assert create_team_result.is_ok()
    team_participant = create_team_result.unwrap()

    add_member_result = tourney_service.add_team_member_by_admin(
        party.id,
        tournament.id,
        team_participant.id,
        new_captain,
        admin_user,
    )
    assert add_member_result.is_ok()

    assign_result = tourney_service.assign_team_captain_by_admin(
        party.id,
        tournament.id,
        team_participant.id,
        new_captain.id,
        admin_user,
    )
    assert assign_result.is_ok()

    participants = tourney_service.get_participants_for_tournament(
        party.id, tournament.id
    )
    updated_participant = next(
        participant
        for participant in participants
        if participant.id == team_participant.id
    )
    assert updated_participant.manager_user_id == new_captain.id

    members = tourney_service.get_team_members_for_participants(
        {team_participant.id}
    )[team_participant.id]
    roles_by_user_id = {member.user_id: member.role.value for member in members}
    assert roles_by_user_id[captain.id] == 'player'
    assert roles_by_user_id[new_captain.id] == 'captain'


def test_admin_can_set_match_slot_participant_for_initial_slots_only(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    users = [make_user('NS_Slot_' + generate_token()) for _ in range(4)]
    for ticket_user in users:
        _assign_party_ticket_to_user(party.id, ticket_user, make_ticket_category)

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-admin-slots-' + generate_token().lower(),
        'NS Admin Slot Assignment',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main Bracket',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    for user in users:
        add_result = tourney_service.add_user_participant_by_admin(
            party.id, tournament.id, user, admin_user
        )
        assert add_result.is_ok()

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()
    matches = generation_result.unwrap()

    first_round_matches = [match for match in matches if match.round_no == 1]
    assert len(first_round_matches) == 2
    match_a = first_round_matches[0]
    match_b = first_round_matches[1]

    slots_by_match_id = tourney_service.get_match_slots(
        {match_a.id, match_b.id}
    )
    match_a_slot_1 = next(
        slot
        for slot in slots_by_match_id[match_a.id]
        if slot.slot_no == 1
    )
    match_b_slot_1 = next(
        slot
        for slot in slots_by_match_id[match_b.id]
        if slot.slot_no == 1
    )
    assert match_b_slot_1.participant_id is not None
    assert match_a_slot_1.participant_id is not None

    clear_result = tourney_service.set_match_slot_participant_by_admin(
        party.id,
        tournament.id,
        match_a.id,
        1,
        None,
        admin_user,
        comment='Clear slot for manual reseeding.',
    )
    assert clear_result.is_ok()

    updated_match = tourney_service.find_match_for_tournament(
        party.id, tournament.id, match_a.id
    )
    assert updated_match is not None
    assert updated_match.state in {MatchState.pending, MatchState.completed}

    duplicate_result = tourney_service.set_match_slot_participant_by_admin(
        party.id,
        tournament.id,
        match_a.id,
        1,
        match_b_slot_1.participant_id,
        admin_user,
        comment='Try duplicate participant in same round.',
    )
    assert duplicate_result.is_err()

    final_match = next(match for match in matches if match.round_no > 1)
    linked_slot_result = tourney_service.set_match_slot_participant_by_admin(
        party.id,
        tournament.id,
        final_match.id,
        1,
        match_a_slot_1.participant_id,
        admin_user,
        comment='Try to override feeder slot.',
    )
    assert linked_slot_result.is_err()


def test_admin_can_delete_tournament_with_existing_data(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_Delete_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-delete-' + generate_token().lower(),
        'NS Delete Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main Bracket',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )
    assert tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).is_ok()

    delete_result = tourney_service.delete_tournament(
        party.id, tournament.id, admin_user
    )
    assert delete_result.is_ok()

    assert (
        tourney_service.find_tournament_for_party(party.id, tournament.id) is None
    )
    assert not tourney_service.get_stages_for_tournament(party.id, tournament.id)
    assert not tourney_service.get_participants_for_tournament(
        party.id, tournament.id
    )
    assert not tourney_service.get_matches_for_tournament(party.id, tournament.id)


def test_delete_tournament_removes_admins_prizes_and_notification_outboxes(
    admin_app, party, admin_user, user
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-delete-refs-' + generate_token().lower(),
        'NS Delete References',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    assert tourney_service.set_tournament_admin_user_ids(
        party.id, tournament.id, {user.id}, admin_user
    ).is_ok()
    assert tourney_service.create_tournament_prize(
        tournament.id, 1, RuleTemplateBodyFormat.markdown, 'First prize'
    ).is_ok()

    now = datetime.utcnow()
    notification_id = uuid4()
    db.session.add(
        DbNetsessionTourneyNotification(
            notification_id, tournament.id, user.id, 'test', {}, now
        )
    )
    db.session.flush()
    db.session.add(
        DbNetsessionTourneyBrowserPushOutbox(uuid4(), notification_id, now)
    )
    db.session.add(
        DbNetsessionTourneyDiscordDmOutbox(uuid4(), notification_id, now)
    )
    db.session.commit()

    delete_result = tourney_service.delete_tournament(
        party.id, tournament.id, admin_user
    )
    assert delete_result.is_ok()

    def _count(model, **filters):
        return len(db.session.scalars(select(model).filter_by(**filters)).all())

    assert _count(DbNetsessionTourneyTournamentAdmin, tournament_id=tournament.id) == 0
    assert _count(DbNetsessionTourneyTournamentPrize, tournament_id=tournament.id) == 0
    assert _count(DbNetsessionTourneyNotification, id=notification_id) == 0
    assert (
        _count(DbNetsessionTourneyBrowserPushOutbox, notification_id=notification_id)
        == 0
    )
    assert (
        _count(DbNetsessionTourneyDiscordDmOutbox, notification_id=notification_id)
        == 0
    )


def test_admin_can_unpublish_live_tournament_without_results(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_Unpublish_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-unpublish-' + generate_token().lower(),
        'NS Unpublish Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main Bracket',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )

    publish_result = tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    )
    assert publish_result.is_ok()
    assert publish_result.unwrap().status == TournamentStatus.live

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    stages_before_unpublish = tourney_service.get_stages_for_tournament(
        party.id, tournament.id
    )
    assert stages_before_unpublish
    assert stages_before_unpublish[0].status == StageStatus.live

    unpublish_result = tourney_service.unpublish_tournament(
        party.id, tournament.id, admin_user
    )
    assert unpublish_result.is_ok()
    assert unpublish_result.unwrap().status == TournamentStatus.draft

    stages_after_unpublish = tourney_service.get_stages_for_tournament(
        party.id, tournament.id
    )
    assert stages_after_unpublish
    assert stages_after_unpublish[0].status == StageStatus.draft


def test_admin_cannot_unpublish_tournament_after_result_was_reported(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger = make_user('NS_UnpublishBlock_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-unpublish-block-' + generate_token().lower(),
        'NS Unpublish Block Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main Bracket',
        {},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert (
        tourney_service.register_user(party.id, tournament.id, challenger).is_ok()
    )

    publish_result = tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    )
    assert publish_result.is_ok()

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()
    match = generation_result.unwrap()[0]

    walkover_result = tourney_service.apply_walkover_result(
        party.id,
        tournament.id,
        match.id,
        admin_user,
        winner_slot=1,
        idempotency_key='unpublish-walkover-key',
        comment='Admin walkover.',
    )
    assert walkover_result.is_ok()

    unpublish_result = tourney_service.unpublish_tournament(
        party.id, tournament.id, admin_user
    )
    assert unpublish_result.is_err()
    assert (
        'cannot be moved back to draft'
        in unpublish_result.unwrap_err().lower()
    )


def test_team_tournament_requires_team_size(admin_app, party, admin_user):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-team-size-required-' + generate_token().lower(),
        'NS Team Size Required',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
    )

    assert create_result.is_err()


def test_solo_tournament_forces_team_size_to_one(admin_app, party, admin_user):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-solo-team-size-' + generate_token().lower(),
        'NS Solo Team Size',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        team_size=7,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()
    assert tournament.team_size == 1


def test_ffa_tournament_allows_team_only_registration_modes(
    admin_app, party, admin_user
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-ffa-team-only-' + generate_token().lower(),
        'NS FFA Team Only',
        TournamentMode.ffa,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=5,
        substitute_count=0,
    )

    assert create_result.is_ok()


def test_stage_type_must_match_tournament_mode(admin_app, party, admin_user):
    duel_tournament_result = tourney_service.create_tournament(
        party.id,
        'ns-stage-mode-duel-' + generate_token().lower(),
        'NS Stage Mode Duel',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert duel_tournament_result.is_ok()
    duel_tournament = duel_tournament_result.unwrap()

    incompatible_ffa_stage_result = tourney_service.create_stage(
        party.id,
        duel_tournament.id,
        StageType.ffa_simple,
        'Invalid FFA Stage',
        {},
        admin_user,
    )
    assert incompatible_ffa_stage_result.is_err()

    ffa_tournament_result = tourney_service.create_tournament(
        party.id,
        'ns-stage-mode-ffa-' + generate_token().lower(),
        'NS Stage Mode FFA',
        TournamentMode.ffa,
        RegistrationMode.solo,
        admin_user,
    )
    assert ffa_tournament_result.is_ok()
    ffa_tournament = ffa_tournament_result.unwrap()

    incompatible_duel_stage_result = tourney_service.create_stage(
        party.id,
        ffa_tournament.id,
        StageType.single_elimination,
        'Invalid Duel Stage',
        {},
        admin_user,
    )
    assert incompatible_duel_stage_result.is_err()


def test_stage_type_compatibility_matrix_for_registration_mode():
    assert tourney_service.is_stage_type_compatible_with_registration_mode(
        StageType.single_elimination,
        RegistrationMode.solo,
    )
    assert tourney_service.is_stage_type_compatible_with_registration_mode(
        StageType.single_elimination,
        RegistrationMode.team_captain_managed,
    )
    assert tourney_service.is_stage_type_compatible_with_registration_mode(
        StageType.ffa_simple,
        RegistrationMode.solo,
    )
    assert tourney_service.is_stage_type_compatible_with_registration_mode(
        StageType.ffa_simple,
        RegistrationMode.team_preformed_only,
    )


def test_round_robin_groups_stage_generates_matches(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-round-robin-groups-' + generate_token().lower(),
        'NS Round Robin Groups',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.round_robin_groups,
        'Groups Stage',
        {'group_size': 4, 'round_count': 2},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    participants = [make_user('NS_RRG_' + generate_token()) for _ in range(6)]
    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert (
            tourney_service.register_user(party.id, tournament.id, participant).is_ok()
        )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()
    assert generation_result.unwrap()


def test_round_robin_groups_with_odd_group_size_generates_bye_matches(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-round-robin-groups-byes-' + generate_token().lower(),
        'NS Round Robin Groups Byes',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.round_robin_groups,
        'Odd Groups Stage',
        {'group_count': 1},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    participants = [make_user('NS_RRG_BYE_' + generate_token()) for _ in range(5)]
    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert (
            tourney_service.register_user(party.id, tournament.id, participant).is_ok()
        )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament.id, stage_id=stage.id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    assert len(db_matches) == 15
    assert sorted({match.round_no for match in db_matches}) == [1, 2, 3, 4, 5]

    match_count_by_round_no = {}
    bye_match_count = 0
    for db_match in db_matches:
        match_count_by_round_no[db_match.round_no] = (
            match_count_by_round_no.get(db_match.round_no, 0) + 1
        )
        db_slots = db.session.scalars(
            select(DbNetsessionTourneyMatchSlot)
            .filter_by(match_id=db_match.id)
            .order_by(DbNetsessionTourneyMatchSlot.slot_no.asc())
        ).all()
        filled_slots = [slot for slot in db_slots if slot.participant_id is not None]
        if len(filled_slots) == 1:
            bye_match_count += 1

    assert match_count_by_round_no == {1: 3, 2: 3, 3: 3, 4: 3, 5: 3}
    assert bye_match_count == 5


def test_builder_round_robin_group_stage_is_not_split_again_after_materialization(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-builder-rr-materialized-' + generate_token().lower(),
        'NS Builder RR Materialized',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        participant_limit=64,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    build_result = tourney_service.build_stage_builder_plan(
        party.id,
        tournament.id,
        generation_basis='ready',
        main_stage_type=StageType.double_elimination,
        main_stage_size=16,
        max_players_per_match=None,
        preliminary_type=StageType.round_robin_groups,
        round_robin_builder_mode='standard',
        round_robin_group_count=None,
        swiss_threshold=None,
        match_duration_minutes=None,
        max_matches_per_round=None,
        break_between_rounds_minutes=None,
        initiator=admin_user,
    )
    assert build_result.is_ok()

    participants = [make_user('NS_BUILDER_RR_' + generate_token()) for _ in range(36)]
    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert (
            tourney_service.register_user(party.id, tournament.id, participant).is_ok()
        )

    stages = tourney_service.get_stages_for_tournament(party.id, tournament.id)
    preliminary_stage = next(
        stage
        for stage in stages
        if (stage.settings or {}).get('builder_role') == 'preliminary'
    )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, preliminary_stage.id, admin_user
    )
    assert generation_result.is_ok()

    stages_after_materialization = tourney_service.get_stages_for_tournament(
        party.id, tournament.id
    )
    group_a_stage = next(
        stage
        for stage in stages_after_materialization
        if (stage.settings or {}).get('builder_role') == 'preliminary_group'
        and (stage.settings or {}).get('builder_group_label') == 'A'
    )
    assert group_a_stage.settings.get('group_count') == 1

    db_matches = db.session.scalars(
        select(DbNetsessionTourneyMatch)
        .filter_by(tournament_id=tournament.id, stage_id=group_a_stage.id)
        .order_by(
            DbNetsessionTourneyMatch.round_no.asc(),
            DbNetsessionTourneyMatch.match_no.asc(),
        )
    ).all()
    assert len(db_matches) == 15
    assert sorted({match.round_no for match in db_matches}) == [1, 2, 3, 4, 5]


def test_deleting_builder_round_robin_container_deletes_generated_groups(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-builder-rr-delete-' + generate_token().lower(),
        'NS Builder RR Delete',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        participant_limit=64,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    build_result = tourney_service.build_stage_builder_plan(
        party.id,
        tournament.id,
        generation_basis='ready',
        main_stage_type=StageType.double_elimination,
        main_stage_size=16,
        max_players_per_match=None,
        preliminary_type=StageType.round_robin_groups,
        round_robin_builder_mode='standard',
        round_robin_group_count=None,
        swiss_threshold=None,
        match_duration_minutes=None,
        max_matches_per_round=None,
        break_between_rounds_minutes=None,
        initiator=admin_user,
    )
    assert build_result.is_ok()

    participants = [make_user('NS_BUILDER_DELETE_' + generate_token()) for _ in range(36)]
    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert (
            tourney_service.register_user(party.id, tournament.id, participant).is_ok()
        )

    stages = tourney_service.get_stages_for_tournament(party.id, tournament.id)
    preliminary_stage = next(
        stage
        for stage in stages
        if (stage.settings or {}).get('builder_role') == 'preliminary'
    )
    main_stage = next(
        stage
        for stage in stages
        if (stage.settings or {}).get('builder_role') == 'main'
    )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, preliminary_stage.id, admin_user
    )
    assert generation_result.is_ok()

    delete_stage_result = tourney_service.delete_stage(
        party.id,
        tournament.id,
        preliminary_stage.id,
        admin_user,
    )
    assert delete_stage_result.is_ok()

    remaining_stages = tourney_service.get_stages_for_tournament(
        party.id, tournament.id
    )
    assert all(
        (stage.settings or {}).get('builder_role') != 'preliminary_group'
        for stage in remaining_stages
    )

    updated_main_stage = next(stage for stage in remaining_stages if stage.id == main_stage.id)
    assert updated_main_stage.settings.get('participant_source_mode') == 'tournament'
    assert 'builder_preliminary_stage_id' not in updated_main_stage.settings
    assert 'qualifier_source_stage_ids' not in updated_main_stage.settings


def test_mode_change_deletes_existing_stages(
    admin_app, party, admin_user
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-mode-switch-' + generate_token().lower(),
        'NS Mode Switch',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_a_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Stage A',
        {},
        admin_user,
    )
    assert stage_a_result.is_ok()
    stage_b_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.swiss,
        'Stage B',
        {'round_count': 3},
        admin_user,
    )
    assert stage_b_result.is_ok()

    update_result = tourney_service.update_tournament(
        party.id,
        tournament.id,
        admin_user,
        mode=TournamentMode.ffa,
        registration_mode=tournament.registration_mode,
        title=tournament.title,
        subtitle=tournament.subtitle,
        logo_url=tournament.logo_url,
        is_sponsored=False,
        sponsor_logo_url=None,
        game=tournament.game,
        starts_at=tournament.starts_at,
        visible_on_site=True,
        rules_page_slug=tournament.rules_page_slug,
        registration_open=tournament.registration_open,
        registration_deadline=tournament.registration_deadline,
        roster_lock_at=tournament.roster_lock_at,
        checkin_open_at=tournament.checkin_open_at,
        checkin_close_at=tournament.checkin_close_at,
        team_size=tournament.team_size,
        participant_limit=tournament.participant_limit,
    )
    assert update_result.is_ok()
    assert update_result.unwrap().mode == TournamentMode.ffa

    stages_after_update = tourney_service.get_stages_for_tournament(
        party.id, tournament.id
    )
    assert not stages_after_update


def test_registration_mode_can_be_changed_in_draft_without_active_participants(
    admin_app, party, admin_user
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-reg-mode-switch-' + generate_token().lower(),
        'NS Registration Mode Switch',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    update_result = tourney_service.update_tournament(
        party.id,
        tournament.id,
        admin_user,
        mode=tournament.mode,
        registration_mode=RegistrationMode.team_captain_managed,
        title=tournament.title,
        subtitle=tournament.subtitle,
        logo_url=tournament.logo_url,
        is_sponsored=False,
        sponsor_logo_url=None,
        game=tournament.game,
        starts_at=tournament.starts_at,
        visible_on_site=True,
        rules_page_slug=tournament.rules_page_slug,
        registration_open=tournament.registration_open,
        registration_deadline=tournament.registration_deadline,
        roster_lock_at=tournament.roster_lock_at,
        checkin_open_at=tournament.checkin_open_at,
        checkin_close_at=tournament.checkin_close_at,
        team_size=5,
        substitute_count=0,
        participant_limit=tournament.participant_limit,
    )
    assert update_result.is_ok()
    assert (
        update_result.unwrap().registration_mode
        == RegistrationMode.team_captain_managed
    )


def test_registration_mode_change_is_blocked_with_active_participants(
    admin_app, party, admin_user, user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-reg-mode-block-' + generate_token().lower(),
        'NS Registration Mode Block',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()

    update_result = tourney_service.update_tournament(
        party.id,
        tournament.id,
        admin_user,
        mode=tournament.mode,
        registration_mode=RegistrationMode.team_captain_managed,
        title=tournament.title,
        subtitle=tournament.subtitle,
        logo_url=tournament.logo_url,
        is_sponsored=False,
        sponsor_logo_url=None,
        game=tournament.game,
        starts_at=tournament.starts_at,
        visible_on_site=True,
        rules_page_slug=tournament.rules_page_slug,
        registration_open=tournament.registration_open,
        registration_deadline=tournament.registration_deadline,
        roster_lock_at=tournament.roster_lock_at,
        checkin_open_at=tournament.checkin_open_at,
        checkin_close_at=tournament.checkin_close_at,
        team_size=5,
        substitute_count=0,
        participant_limit=tournament.participant_limit,
    )
    assert update_result.is_err()
    assert 'no active participants' in update_result.unwrap_err().lower()


def test_admin_can_update_and_delete_stage(
    admin_app, party, admin_user
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-stage-edit-delete-' + generate_token().lower(),
        'NS Stage Edit/Delete',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Original Stage',
        {'round_count': 1},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    update_stage_result = tourney_service.update_stage(
        party.id,
        tournament.id,
        stage.id,
        StageType.swiss,
        'Updated Stage',
        {'round_count': 4},
        admin_user,
    )
    assert update_stage_result.is_ok()
    updated_stage = update_stage_result.unwrap()
    assert updated_stage.type == StageType.swiss
    assert updated_stage.name == 'Updated Stage'
    assert updated_stage.settings.get('round_count') == 4

    delete_stage_result = tourney_service.delete_stage(
        party.id,
        tournament.id,
        stage.id,
        admin_user,
    )
    assert delete_stage_result.is_ok()
    remaining_stages = tourney_service.get_stages_for_tournament(
        party.id,
        tournament.id,
    )
    assert not remaining_stages


def test_deleting_stage_renumbers_remaining_stages_without_unique_conflict(
    admin_app, party, admin_user
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-stage-delete-renumber-' + generate_token().lower(),
        'NS Stage Delete Renumber',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    created_stages = []
    for index in range(1, 10):
        stage_result = tourney_service.create_stage(
            party.id,
            tournament.id,
            StageType.single_elimination,
            f'Stage {index}',
            {'round_count': 1},
            admin_user,
        )
        assert stage_result.is_ok()
        created_stages.append(stage_result.unwrap())

    delete_stage_result = tourney_service.delete_stage(
        party.id,
        tournament.id,
        created_stages[0].id,
        admin_user,
    )
    assert delete_stage_result.is_ok()

    remaining_stages = tourney_service.get_stages_for_tournament(
        party.id,
        tournament.id,
    )
    assert [stage.order_no for stage in remaining_stages] == list(range(1, 9))
    assert [stage.name for stage in remaining_stages] == [
        f'Stage {index}' for index in range(2, 10)
    ]


def test_ffa_single_elimination_stage_generates_knockout_matches(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-ffa-knockout-' + generate_token().lower(),
        'NS FFA Knockout',
        TournamentMode.ffa,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.ffa_single_elimination,
        'FFA Knockout Stage',
        {'max_players_per_match': 4},
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    participants = [make_user('NS_FFAK_' + generate_token()) for _ in range(9)]
    for participant in participants:
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert (
            tourney_service.register_user(party.id, tournament.id, participant).is_ok()
        )

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()
    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    assert matches
    assert max(match.round_no for match in matches) >= 2

    slots_by_match_id = tourney_service.get_match_slots({match.id for match in matches})
    round1_matches = [match for match in matches if match.round_no == 1]
    round1_player_counts = [
        len(
            [
                slot
                for slot in slots_by_match_id[match.id]
                if slot.participant_id is not None
            ]
        )
        for match in round1_matches
    ]
    # Players are distributed evenly over the first round (9 players with at
    # most 4 per match -> 3+3+3), so there is no single-player match.
    assert sum(round1_player_counts) == 9
    assert max(round1_player_counts) <= 4
    assert max(round1_player_counts) - min(round1_player_counts) <= 1
    assert 1 not in round1_player_counts


def test_join_team_respects_team_size(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    teammate = make_user('NS_TeamMate_' + generate_token())
    extra_member = make_user('NS_Extra_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-team-size-' + generate_token().lower(),
        'NS Team Size Demo',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=2,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, teammate, make_ticket_category
    )
    _assign_party_ticket_to_user(
        party.id, extra_member, make_ticket_category
    )

    team_result = tourney_service.create_team_for_captain(
        party.id, tournament.id, user, 'Team Alpha'
    )
    assert team_result.is_ok()
    participant = team_result.unwrap()

    invite_code = db.session.scalar(
        select(DbNetsessionTourneyParticipant.invite_code).filter_by(
            id=participant.id
        )
    )
    assert invite_code

    assert tourney_service.join_team_by_invite_code(
        party.id, tournament.id, invite_code, teammate
    ).is_ok()

    join_extra_result = tourney_service.join_team_by_invite_code(
        party.id, tournament.id, invite_code, extra_member
    )
    assert join_extra_result.is_err()
    assert 'already full' in join_extra_result.unwrap_err().lower()


def test_user_registration_requires_ticket_for_party(
    admin_app, party, admin_user, make_user
):
    user_without_ticket = make_user('NS_NoTicket_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-ticket-required-' + generate_token().lower(),
        'NS Ticket Required',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    register_without_ticket_result = tourney_service.register_user(
        party.id,
        tournament.id,
        user_without_ticket,
    )
    assert register_without_ticket_result.is_err()
    assert (
        'ticket for this party'
        in register_without_ticket_result.unwrap_err().lower()
    )


def test_user_registration_works_with_ticket_for_party(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    user_with_ticket = make_user('NS_WithTicket_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-ticket-allowed-' + generate_token().lower(),
        'NS Ticket Allowed',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(
        party.id, user_with_ticket, make_ticket_category
    )

    register_result = tourney_service.register_user(
        party.id,
        tournament.id,
        user_with_ticket,
    )
    assert register_result.is_ok()


def test_team_only_tournament_blocks_solo_register_route(
    admin_app, party, admin_user, user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-team-only-register-block-' + generate_token().lower(),
        'NS Team Only Register Block',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=5,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)

    register_result = tourney_service.register_user(
        party.id,
        tournament.id,
        user,
    )
    assert register_result.is_err()
    assert 'team-anmeldung' in register_result.unwrap_err().lower()


def test_team_captain_can_toggle_ready_state(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    teammate = make_user('NS_ReadyMate_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-ready-toggle-' + generate_token().lower(),
        'NS Ready Toggle',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=2,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(party.id, teammate, make_ticket_category)

    team_result = tourney_service.create_team_for_captain(
        party.id,
        tournament.id,
        user,
        'Team Ready',
    )
    assert team_result.is_ok()
    team = team_result.unwrap()

    not_ready_yet_result = tourney_service.set_managed_team_ready_state(
        party.id,
        tournament.id,
        team.id,
        user,
        ready=True,
    )
    assert not_ready_yet_result.is_err()
    assert 'not complete' in not_ready_yet_result.unwrap_err().lower()

    invite_code = db.session.scalar(
        select(DbNetsessionTourneyParticipant.invite_code).filter_by(id=team.id)
    )
    assert invite_code

    join_result = tourney_service.join_team_by_invite_code(
        party.id,
        tournament.id,
        invite_code,
        teammate,
    )
    assert join_result.is_ok()

    set_ready_result = tourney_service.set_managed_team_ready_state(
        party.id,
        tournament.id,
        team.id,
        user,
        ready=True,
    )
    assert set_ready_result.is_ok()
    assert set_ready_result.unwrap().status == ParticipantStatus.ready

    set_forming_result = tourney_service.set_managed_team_ready_state(
        party.id,
        tournament.id,
        team.id,
        user,
        ready=False,
    )
    assert set_forming_result.is_ok()
    assert set_forming_result.unwrap().status == ParticipantStatus.forming


def test_captain_can_add_and_remove_team_member(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    teammate = make_user('NS_AddRemove_' + generate_token())

    create_result = tourney_service.create_tournament(
        party.id,
        'ns-add-remove-' + generate_token().lower(),
        'NS Team Member Management',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=3,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, teammate, make_ticket_category
    )

    team_result = tourney_service.create_team_for_captain(
        party.id, tournament.id, user, 'Team Manage'
    )
    assert team_result.is_ok()
    participant = team_result.unwrap()

    add_result = tourney_service.add_team_member_by_captain(
        party.id,
        tournament.id,
        participant.id,
        teammate,
        user,
    )
    assert add_result.is_ok()

    members_after_add = tourney_service.get_team_members_for_participants(
        {participant.id}
    )
    member_user_ids_after_add = {
        member.user_id
        for member in members_after_add.get(participant.id, [])
    }
    assert member_user_ids_after_add == {user.id, teammate.id}

    remove_result = tourney_service.remove_team_member_by_captain(
        party.id,
        tournament.id,
        participant.id,
        teammate.id,
        user,
    )
    assert remove_result.is_ok()

    members_after_remove = tourney_service.get_team_members_for_participants(
        {participant.id}
    )
    member_user_ids_after_remove = {
        member.user_id
        for member in members_after_remove.get(participant.id, [])
    }
    assert member_user_ids_after_remove == {user.id}


def test_captain_can_regenerate_team_invite_code(
    admin_app, party, admin_user, user, make_ticket_category
):
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-regen-invite-' + generate_token().lower(),
        'NS Invite Regeneration',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=5,
        substitute_count=0,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)

    team_result = tourney_service.create_team_for_captain(
        party.id, tournament.id, user, 'Team Invite'
    )
    assert team_result.is_ok()
    participant = team_result.unwrap()

    invite_code_before = db.session.scalar(
        select(DbNetsessionTourneyParticipant.invite_code).filter_by(
            id=participant.id
        )
    )
    assert invite_code_before

    regenerate_result = tourney_service.regenerate_team_invite_code_for_manager(
        party.id,
        tournament.id,
        participant.id,
        user,
    )
    assert regenerate_result.is_ok()
    invite_code_after = regenerate_result.unwrap()
    assert invite_code_after
    assert invite_code_after != invite_code_before

    lookup_result = tourney_service.get_team_invite_code_for_manager(
        party.id,
        tournament.id,
        participant.id,
        user.id,
    )
    assert lookup_result.is_ok()
    assert lookup_result.unwrap() == invite_code_after


def test_stage_scheduling_uses_stage_timing_settings(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    challenger_a = make_user('NS_ScheduleA_' + generate_token())
    challenger_b = make_user('NS_ScheduleB_' + generate_token())
    challenger_c = make_user('NS_ScheduleC_' + generate_token())

    starts_at = datetime(2026, 1, 10, 12, 0, 0)
    create_result = tourney_service.create_tournament(
        party.id,
        'ns-schedule-' + generate_token().lower(),
        'NS Schedule Demo',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        starts_at=starts_at,
    )
    assert create_result.is_ok()
    tournament = create_result.unwrap()

    stage_result = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Timed Stage',
        {
            'match_duration_minutes': 30,
            'max_matches_per_round': 1,
            'break_between_rounds_minutes': 15,
        },
        admin_user,
    )
    assert stage_result.is_ok()
    stage = stage_result.unwrap()

    _assign_party_ticket_to_user(party.id, user, make_ticket_category)
    _assign_party_ticket_to_user(
        party.id, challenger_a, make_ticket_category
    )
    _assign_party_ticket_to_user(
        party.id, challenger_b, make_ticket_category
    )
    _assign_party_ticket_to_user(
        party.id, challenger_c, make_ticket_category
    )

    assert tourney_service.register_user(party.id, tournament.id, user).is_ok()
    assert tourney_service.register_user(party.id, tournament.id, challenger_a).is_ok()
    assert tourney_service.register_user(party.id, tournament.id, challenger_b).is_ok()
    assert tourney_service.register_user(party.id, tournament.id, challenger_c).is_ok()

    generation_result = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    )
    assert generation_result.is_ok()

    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    assert len(matches) == 4

    round1_match1 = next(
        match
        for match in matches
        if match.round_no == 1 and match.match_no == 1
    )
    round1_match2 = next(
        match
        for match in matches
        if match.round_no == 1 and match.match_no == 2
    )
    round2_match1 = next(
        match
        for match in matches
        if match.round_no == 2 and match.match_no == 3
    )
    round2_match2 = next(
        match
        for match in matches
        if match.round_no == 2 and match.match_no == 4
    )

    assert round1_match1.scheduled_at == starts_at
    assert round1_match2.scheduled_at == datetime(2026, 1, 10, 12, 30, 0)
    assert round2_match1.scheduled_at == datetime(2026, 1, 10, 13, 15, 0)
    assert round2_match2.scheduled_at == datetime(2026, 1, 10, 13, 45, 0)


def test_swiss_stage_advances_through_all_rounds(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament = tourney_service.create_tournament(
        party.id,
        'ns-swiss-flow-' + generate_token().lower(),
        'NS Swiss Flow',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.swiss,
        'Swiss',
        {'round_count': 3},
        admin_user,
    ).unwrap()
    for _ in range(4):
        participant = make_user('NS_SwissFlow_' + generate_token())
        _assign_party_ticket_to_user(party.id, participant, make_ticket_category)
        assert tourney_service.register_user(
            party.id, tournament.id, participant
        ).is_ok()
    assert tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    assert tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).is_ok()

    # Used to fail with a NameError when seeding round 2.
    _complete_ready_matches(
        party.id, tournament.id, admin_user, excluded_match_ids=set()
    )

    matches = tourney_service.get_matches_for_tournament(party.id, tournament.id)
    assert max(match.round_no for match in matches) == 3
    assert all(match.state.value == 'completed' for match in matches)


def test_player_cannot_report_in_admin_only_stage(
    admin_app, party, admin_user, make_user, make_ticket_category
):
    tournament = tourney_service.create_tournament(
        party.id,
        'ns-admin-only-' + generate_token().lower(),
        'NS Admin Only',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main',
        {'result_report_mode': 'admin_only'},
        admin_user,
    ).unwrap()
    players = [make_user('NS_AdminOnly_' + generate_token()) for _ in range(2)]
    for player in players:
        _assign_party_ticket_to_user(party.id, player, make_ticket_category)
        assert tourney_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
    assert tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    match = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()[0]

    player_result = tourney_service.report_result(
        party.id,
        tournament.id,
        match.id,
        players[0].id,
        idempotency_key='admin-only-player-' + generate_token(),
        winner_slot=1,
        score={'display': '1:0'},
    )
    assert player_result.is_err()
    assert 'nur Admins' in player_result.unwrap_err()

    admin_result = tourney_service.report_result(
        party.id,
        tournament.id,
        match.id,
        admin_user.id,
        idempotency_key='admin-only-admin-' + generate_token(),
        winner_slot=1,
        score={'display': '1:0'},
        actor_is_admin_or_referee=True,
        admin_comment='Admin enters result.',
    )
    assert admin_result.is_ok()


@pytest.mark.parametrize(
    ('stage_type', 'grand_final_winner_slot', 'expected_states'),
    [
        # Loser of match 1 wins the grand final: in the double grand final
        # variant the reset match has to be played.
        (StageType.double_elimination, 2, ['completed', 'completed']),
        (
            StageType.double_elimination_double_grand_final,
            2,
            ['completed', 'completed', 'ready'],
        ),
        # Winner of match 1 wins again: reset match is skipped.
        (
            StageType.double_elimination_double_grand_final,
            1,
            ['completed', 'completed', 'completed'],
        ),
    ],
)
def test_double_elimination_with_two_participants_gives_second_chance(
    admin_app,
    party,
    admin_user,
    make_user,
    make_ticket_category,
    stage_type,
    grand_final_winner_slot,
    expected_states,
):
    tournament = tourney_service.create_tournament(
        party.id,
        'ns-de-two-' + generate_token().lower(),
        'NS DE Two',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = tourney_service.create_stage(
        party.id, tournament.id, stage_type, 'DE', {}, admin_user
    ).unwrap()
    for _ in range(2):
        player = make_user('NS_DETwo_' + generate_token())
        _assign_party_ticket_to_user(party.id, player, make_ticket_category)
        assert tourney_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
    assert tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()

    def matches():
        return sorted(
            tourney_service.get_matches_for_tournament(party.id, tournament.id),
            key=lambda match: match.match_no,
        )

    for match, winner_slot in zip(matches()[:2], (1, grand_final_winner_slot)):
        assert tourney_service.report_result(
            party.id,
            tournament.id,
            match.id,
            admin_user.id,
            idempotency_key='de-two-' + generate_token(),
            winner_slot=winner_slot,
            score={'display': '1:0'},
            actor_is_admin_or_referee=True,
            admin_comment='Test',
        ).is_ok()

    assert [match.state.value for match in matches()] == expected_states


def test_admin_cannot_add_user_without_ticket(admin_app, party, admin_user, make_user):
    tournament = tourney_service.create_tournament(
        party.id,
        'ns-no-ticket-' + generate_token().lower(),
        'NS No Ticket',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    candidate = make_user('NS_NoTicket_' + generate_token())

    result = tourney_service.add_user_participant_by_admin(
        party.id, tournament.id, candidate, admin_user
    )

    assert result.is_err()
    assert 'ticket' in result.unwrap_err().lower()


def _assign_party_ticket_to_user(party_id, user, make_ticket_category) -> None:
    category = make_ticket_category(
        party_id, 'NS-Ticket-' + generate_token()
    )
    ticket = ticket_creation_service.create_ticket(category, user)
    appoint_result = ticket_user_management_service.appoint_user(
        ticket.id, user, user
    )
    assert appoint_result.is_ok()


def _complete_ready_matches(
    party_id, tournament_id, admin_user, *, excluded_match_ids
) -> None:
    """Report slot 1 as winner for every ready match (except the excluded
    ones) until no such match is left."""
    for _ in range(100):
        ready_matches = [
            match
            for match in tourney_service.get_matches_for_tournament(
                party_id, tournament_id
            )
            if match.state.value == 'ready' and match.id not in excluded_match_ids
        ]
        if not ready_matches:
            return

        for match in ready_matches:
            result = tourney_service.report_result(
                party_id,
                tournament_id,
                match.id,
                admin_user.id,
                idempotency_key='complete-ready-' + generate_token(),
                winner_slot=1,
                score={'display': '1:0'},
                actor_is_admin_or_referee=True,
                admin_comment='Test bracket progression',
            )
            assert result.is_ok()

    raise AssertionError('Bracket did not settle.')


def test_tournament_cannot_be_closed_while_matches_are_open(
    admin_app, party, admin_user, user, make_user, make_ticket_category
):
    opponent = make_user('NS_Close_' + generate_token())
    tournament = tourney_service.create_tournament(
        party.id,
        'ns-close-' + generate_token().lower(),
        'NS Close',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = tourney_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'Main',
        {},
        admin_user,
    ).unwrap()
    for player in (user, opponent):
        _assign_party_ticket_to_user(party.id, player, make_ticket_category)
        assert tourney_service.register_user(
            party.id, tournament.id, player
        ).is_ok()
    assert tourney_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()
    final = tourney_service.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()[0]

    blocked = tourney_service.close_tournament(
        party.id, tournament.id, admin_user
    )
    assert blocked.is_err()
    assert 'noch 1 Matches offen' in blocked.unwrap_err()

    assert tourney_service.report_result(
        party.id,
        tournament.id,
        final.id,
        admin_user.id,
        idempotency_key='close-final',
        winner_slot=1,
        score={'display': '1:0', 'slots': {'1': 1, '2': 0}},
        actor_is_admin_or_referee=True,
    ).is_ok()

    assert tourney_service.close_tournament(
        party.id, tournament.id, admin_user
    ).is_ok()


def _make_coin_team_tournament(
    party, admin_user, make_user, make_ticket_category, coin_charge_mode
):
    """Team tournament (size 2, 3 coins) with a complete team that pays
    according to `coin_charge_mode`; returns (tournament, team, captain,
    mate)."""
    assert tourney_service.configure_coin_settings(
        party.id,
        admin_user,
        enabled=True,
        default_coin_amount=10,
        ticket_category_coin_amounts={},
    ).is_ok()
    tournament = tourney_service.create_tournament(
        party.id,
        'ns-coins-' + generate_token().lower(),
        'NS Coins',
        TournamentMode.duel,
        RegistrationMode.team_captain_managed,
        admin_user,
        team_size=2,
        substitute_count=0,
        coin_cost=3,
        coin_charge_mode=coin_charge_mode,
    ).unwrap()
    captain = make_user('NS_CoinCap_' + generate_token())
    mate = make_user('NS_CoinMate_' + generate_token())
    for player in (captain, mate):
        _assign_party_ticket_to_user(party.id, player, make_ticket_category)
    team = tourney_service.create_team_for_captain(
        party.id, tournament.id, captain, 'Coin Team'
    ).unwrap()
    invite_code = db.session.scalar(
        select(DbNetsessionTourneyParticipant.invite_code).filter_by(id=team.id)
    )
    assert tourney_service.join_team_by_invite_code(
        party.id, tournament.id, invite_code, mate
    ).is_ok()
    return tournament, team, captain, mate


def _coins(party, user) -> int:
    return tourney_service.get_user_coin_balance(
        party.id, user.id
    ).available_coins


def test_refund_after_captain_change_goes_to_former_captain(
    admin_app, isolated_party, admin_user, make_user, make_ticket_category
):
    party = isolated_party
    tournament, team, captain, mate = _make_coin_team_tournament(
        party, admin_user, make_user, make_ticket_category,
        CoinChargeMode.captain_only,
    )
    assert (_coins(party, captain), _coins(party, mate)) == (7, 10)

    assert tourney_service.assign_team_captain_by_admin(
        party.id, tournament.id, team.id, mate.id, admin_user
    ).is_ok()
    assert tourney_service.deregister_user(
        party.id, tournament.id, mate
    ).is_ok()

    # The former captain paid and gets the coins back; nobody else gains.
    assert (_coins(party, captain), _coins(party, mate)) == (10, 10)


def test_removed_member_gets_coins_back_and_team_is_no_longer_ready(
    admin_app, isolated_party, admin_user, make_user, make_ticket_category
):
    party = isolated_party
    tournament, team, captain, mate = _make_coin_team_tournament(
        party, admin_user, make_user, make_ticket_category,
        CoinChargeMode.all_members,
    )
    assert tourney_service.set_managed_team_ready_state(
        party.id, tournament.id, team.id, captain, ready=True
    ).is_ok()
    assert _coins(party, mate) == 7

    assert tourney_service.remove_team_member_by_admin(
        party.id, tournament.id, team.id, mate.id, admin_user
    ).is_ok()

    assert _coins(party, mate) == 10
    status = db.session.scalar(
        select(DbNetsessionTourneyParticipant.status).filter_by(id=team.id)
    )
    assert status == ParticipantStatus.forming.value


def test_team_is_no_longer_ready_when_a_member_leaves(
    admin_app, isolated_party, admin_user, make_user, make_ticket_category
):
    party = isolated_party
    tournament, team, captain, mate = _make_coin_team_tournament(
        party, admin_user, make_user, make_ticket_category,
        CoinChargeMode.captain_only,
    )
    assert tourney_service.set_managed_team_ready_state(
        party.id, tournament.id, team.id, captain, ready=True
    ).is_ok()

    assert tourney_service.deregister_user(
        party.id, tournament.id, mate
    ).is_ok()

    status = db.session.scalar(
        select(DbNetsessionTourneyParticipant.status).filter_by(id=team.id)
    )
    assert status == ParticipantStatus.forming.value


def test_changing_a_rule_template_slug_keeps_tournaments_linked(
    admin_app, isolated_party, admin_user
):
    party = isolated_party
    template = tourney_service.create_tournament_rule_template(
        party.id, 'rules-old', 'Regeln', RuleTemplateBodyFormat.markdown, 'Fair'
    ).unwrap()
    tournament = tourney_service.create_tournament(
        party.id,
        'ns-rules-' + generate_token().lower(),
        'NS Rules',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
        rules_page_slug='rules-old',
    ).unwrap()

    assert tourney_service.update_tournament_rule_template(
        template.id,
        'rules-new',
        'Regeln',
        RuleTemplateBodyFormat.markdown,
        'Fair',
    ).is_ok()

    reloaded = tourney_service.find_tournament_for_party(party.id, tournament.id)
    assert reloaded.rules_page_slug == 'rules-new'
