"""Tournament detail (matches with slots and results) and standings for
read-only API clients such as Screens."""

import pytest

from byceps.services.netsession_tourney import (
    match_generation,
    match_queries,
    registration_service,
    result_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_prize_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    RuleTemplateBodyFormat,
    StageType,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token


BASE = 'http://api.ns.test/v1/ns-tourneys/tournaments'


@pytest.fixture
def bracket(
    admin_app, make_party, brand, admin_user, make_user, make_ticket_category
):
    """A live single elimination with 4 players, first round not played."""
    party = make_party(brand)
    tournament = tournament_service.create_tournament(
        party.id,
        'ns-api-' + generate_token().lower(),
        'NS API Cup',
        TournamentMode.duel,
        RegistrationMode.solo,
        admin_user,
    ).unwrap()
    stage = stage_service.create_stage(
        party.id,
        tournament.id,
        StageType.single_elimination,
        'KO',
        {},
        admin_user,
    ).unwrap()
    category = make_ticket_category(party.id, 'NS-API-' + generate_token())
    for no in range(4):
        player = make_user(f'NS_Api_{no}_' + generate_token())
        ticket = ticket_creation_service.create_ticket(category, player)
        ticket_user_management_service.appoint_user(
            ticket.id, player, player
        ).unwrap()
        registration_service.register_user(
            party.id, tournament.id, player
        ).unwrap()
    tournament_lifecycle_service.publish_tournament(
        party.id, tournament.id, admin_user
    ).unwrap()
    match_generation.generate_stage_matches(
        party.id, tournament.id, stage.id, admin_user
    ).unwrap()
    tournament_prize_service.create_tournament_prize(
        tournament.id,
        1,
        RuleTemplateBodyFormat.markdown,
        '**be quiet! Pure Base 500**\n\nvon be quiet!',
    ).unwrap()
    return party, tournament


def _complete_ready_matches(party, tournament, admin_user) -> None:
    for _ in range(10):
        ready = [
            match
            for match in match_queries.get_matches_for_tournament(
                party.id, tournament.id
            )
            if match.state.value == 'ready'
        ]
        if not ready:
            return
        for match in ready:
            result_service.report_result(
                party.id,
                tournament.id,
                match.id,
                admin_user.id,
                idempotency_key='api-' + generate_token(),
                winner_slot=1,
                score={'display': '16:12'},
                actor_is_admin_or_referee=True,
                admin_comment='API test',
            ).unwrap()


def test_endpoints_require_token_with_read_permission(
    ns_api_client, read_headers, other_headers, bracket
):
    party, tournament = bracket
    for url in (
        f'{BASE}?party_id={party.id}',
        f'{BASE}/{tournament.id}?party_id={party.id}',
        f'{BASE}/{tournament.id}/standings?party_id={party.id}',
    ):
        assert ns_api_client.get(url).status_code == 401
        assert ns_api_client.get(url, headers=other_headers).status_code == 403
        assert ns_api_client.get(url, headers=read_headers).status_code == 200


def test_open_bracket_shows_slot_sources_and_no_standings(
    ns_api_client, read_headers, bracket
):
    party, tournament = bracket
    url = f'{BASE}/{tournament.id}?party_id={party.id}'
    data = ns_api_client.get(url, headers=read_headers).get_json()

    first_round = [m for m in data['matches'] if m['round_no'] == 1]
    final = [m for m in data['matches'] if m['round_no'] == 2][0]
    assert all(m['result'] is None for m in data['matches'])
    assert all(slot['name'] for m in first_round for slot in m['slots'])
    first_round_ids = {m['id'] for m in first_round}
    for slot in final['slots']:
        assert slot['participant_id'] is None
        assert slot['source']['outcome'] == 'winner'
        assert slot['source']['match_id'] in first_round_ids

    standings = ns_api_client.get(
        f'{BASE}/{tournament.id}/standings?party_id={party.id}',
        headers=read_headers,
    ).get_json()
    assert standings['final'] is False
    assert standings['standings'] == []


def test_finished_bracket_shows_results_and_final_standings(
    ns_api_client, read_headers, bracket, admin_user
):
    party, tournament = bracket
    _complete_ready_matches(party, tournament, admin_user)

    data = ns_api_client.get(
        f'{BASE}/{tournament.id}?party_id={party.id}', headers=read_headers
    ).get_json()
    final = [m for m in data['matches'] if m['round_no'] == 2][0]
    assert final['state'] == 'completed'
    assert final['result']['winner_slot'] == 1
    assert final['result']['score_display'] == '16:12'
    assert final['result']['scores'] == {'1': 16, '2': 12}
    assert final['result']['confirmed'] is True
    assert final['result']['walkover'] is False
    assert data['tournament']['starts_at'] is None or data['tournament'][
        'starts_at'
    ].endswith('+00:00')

    standings = ns_api_client.get(
        f'{BASE}/{tournament.id}/standings?party_id={party.id}',
        headers=read_headers,
    ).get_json()
    assert standings['final'] is True
    first, second = standings['standings'][:2]
    assert first['rank'] == 1
    assert first['name'] == final['slots'][0]['name']
    assert first['prize']['title'] == 'be quiet! Pure Base 500'
    assert second['rank'] == 2
    assert second['prize'] is None
    for row in standings['standings']:
        same = [r for r in standings['standings'] if r['rank'] == row['rank']]
        assert row['rank_from'] == row['rank']
        assert row['rank_to'] == row['rank'] + len(same) - 1


def test_unchanged_answer_gets_304(ns_api_client, read_headers, bracket):
    party, tournament = bracket
    url = f'{BASE}/{tournament.id}?party_id={party.id}'
    first = ns_api_client.get(url, headers=read_headers)
    etag = first.headers['ETag']

    second = ns_api_client.get(
        url, headers={**read_headers, 'If-None-Match': etag}
    )
    assert second.status_code == 304
