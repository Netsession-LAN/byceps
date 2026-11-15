"""Format details for Screens: double elimination brackets and labels,
byes, next matches, tables of league/Swiss stages, FFA slots."""

from byceps.services.netsession_tourney import match_queries, result_service
from byceps.services.netsession_tourney.models import StageType, TournamentMode

from tests.helpers import generate_token


BASE = 'http://api.ns.test/v1/ns-tourneys/tournaments'


def _detail(client, headers, party, tournament):
    return client.get(
        f'{BASE}/{tournament.id}?party_id={party.id}', headers=headers
    ).get_json()


def _play_ready(party, tournament, admin_user, *, rounds=50):
    for _ in range(rounds):
        ready = [
            m
            for m in match_queries.get_matches_for_tournament(
                party.id, tournament.id
            )
            if m.state.value == 'ready'
        ]
        if not ready:
            return
        for match in ready:
            result_service.report_result(
                party.id,
                tournament.id,
                match.id,
                admin_user.id,
                idempotency_key='fmt-' + generate_token(),
                winner_slot=1,
                score={'display': '2:1'},
                actor_is_admin_or_referee=True,
                admin_comment='API test',
            ).unwrap()


def test_double_elimination_brackets_and_next_matches(
    ns_api_client, read_headers, make_live_tourney
):
    party, tournament = make_live_tourney(
        TournamentMode.duel, StageType.double_elimination, 4
    )
    data = _detail(ns_api_client, read_headers, party, tournament)
    matches = {m['id']: m for m in data['matches']}

    brackets = {m['bracket'] for m in matches.values()}
    assert {'upper', 'lower', 'grand_final'} <= brackets
    assert all(m['round_label'] for m in matches.values())
    grand_final = next(
        m for m in matches.values() if m['bracket'] == 'grand_final'
    )
    assert grand_final['round_label'] == 'Grand Final'
    assert grand_final['reset'] is False
    assert grand_final['next_match_id'] is None

    first_round = [
        m
        for m in matches.values()
        if m['bracket'] == 'upper' and m['round_no'] == 1
    ]
    assert first_round
    for match in first_round:
        assert matches[match['next_match_id']]['bracket'] == 'upper'
        loser_target = matches[match['loser_next_match_id']]
        assert loser_target['bracket'] == 'lower'
        assert any(
            slot['source'] == {'match_id': match['id'], 'outcome': 'loser'}
            for slot in loser_target['slots']
        )


def test_single_elimination_with_three_players_marks_the_bye(
    ns_api_client, read_headers, make_live_tourney
):
    party, tournament = make_live_tourney(
        TournamentMode.duel, StageType.single_elimination, 3
    )
    data = _detail(ns_api_client, read_headers, party, tournament)
    slots = [slot for m in data['matches'] for slot in m['slots']]
    byes = [slot for slot in slots if slot['bye']]
    assert len(byes) == 1
    assert byes[0]['participant_id'] is None
    open_slots = [
        s for s in slots if s['participant_id'] is None and not s['bye']
    ]
    assert all(s['source'] is not None for s in open_slots)


def test_league_table_and_tournament_phase(
    ns_api_client, read_headers, make_live_tourney, admin_user
):
    party, tournament = make_live_tourney(
        TournamentMode.duel, StageType.league, 3
    )
    _play_ready(party, tournament, admin_user)
    data = _detail(ns_api_client, read_headers, party, tournament)

    assert data['tournament']['phase'] == 'running'
    (stage,) = data['stages']
    assert stage['phase'] in {'planned', 'running', 'completed'}
    (group,) = stage['groups']
    standings = group['standings']
    # With 3 players every round has a bye match; it does not count.
    played_matches = [
        m
        for m in data['matches']
        if m['result'] and all(s['participant_id'] for s in m['slots'])
    ]
    assert played_matches
    assert len(standings) == 3
    assert sum(row['played'] for row in standings) == 2 * len(played_matches)
    assert sum(row['wins'] for row in standings) == len(played_matches)
    assert standings[0]['rank'] == 1
    assert standings[0]['points'] == 3 * standings[0]['wins']
    assert standings[0]['diff'] == (
        standings[0]['score_for'] - standings[0]['score_against']
    )
    assert all(row['draws'] == 0 for row in standings)


def test_swiss_table_has_buchholz_and_round_count(
    ns_api_client, read_headers, make_live_tourney, admin_user
):
    party, tournament = make_live_tourney(
        TournamentMode.duel, StageType.swiss, 4, {'round_count': 3}
    )
    _play_ready(party, tournament, admin_user, rounds=1)
    data = _detail(ns_api_client, read_headers, party, tournament)
    (stage,) = data['stages']
    assert stage['rounds_total'] == 3
    rows = stage['groups'][0]['standings']
    assert rows
    assert all('buchholz' in row['tiebreak'] for row in rows)


def test_ffa_match_lists_all_players(
    ns_api_client, read_headers, make_live_tourney, admin_user
):
    party, tournament = make_live_tourney(
        TournamentMode.ffa,
        StageType.ffa_simple,
        4,
        {'max_players_per_match': 8},
    )
    (match,) = match_queries.get_matches_for_tournament(
        party.id, tournament.id
    )
    result_service.report_result(
        party.id,
        tournament.id,
        match.id,
        admin_user.id,
        idempotency_key='ffa-' + generate_token(),
        winner_slot=1,
        ranking={'placements': {'1': 1, '2': 2, '3': 3, '4': 4}},
        actor_is_admin_or_referee=True,
        admin_comment='API test',
    ).unwrap()
    data = _detail(ns_api_client, read_headers, party, tournament)
    (api_match,) = data['matches']
    assert len(api_match['slots']) == 4
    assert [s['placement'] for s in api_match['slots']] == [1, 2, 3, 4]
    assert all(s['advances'] is False for s in api_match['slots'])


def test_slot_of_removed_participant_keeps_name_and_is_flagged(
    ns_api_client, read_headers, make_live_tourney, admin_user
):
    from byceps.services.netsession_tourney import (
        participant_admin_service,
        tournament_queries,
    )

    party, tournament = make_live_tourney(
        TournamentMode.duel, StageType.league, 4
    )
    removed = tournament_queries.get_participants_for_tournament(
        party.id, tournament.id
    )[0]
    participant_admin_service.remove_participant_by_admin(
        party.id, tournament.id, removed.id, admin_user, comment='API test'
    ).unwrap()

    data = _detail(ns_api_client, read_headers, party, tournament)
    assert str(removed.id) not in {p['id'] for p in data['participants']}
    slots = [
        slot
        for m in data['matches']
        for slot in m['slots']
        if slot['participant_id'] == str(removed.id)
    ]
    assert slots
    assert all(s['name'] == removed.name and s['withdrawn'] for s in slots)
