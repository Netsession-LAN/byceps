"""Tournament creation wizard: the way through all steps."""

from datetime import datetime

import pytest

from byceps.services.netsession_tourney import (
    logo_service,
    tournament_admin_service,
    tournament_rule_template_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    CoinChargeMode,
    RegistrationMode,
    RuleTemplateBodyFormat,
    TournamentMode,
)

from .t1_wizard_steps import (
    create_wizard_party,
    find_tournament,
    is_selected,
    png,
    post_details,
    post_format,
    post_schedule,
)


@pytest.fixture
def wizard_party(make_party, brand):
    return create_wizard_party(make_party, brand)


@pytest.fixture
def assets(wizard_party, tourney_admin):
    """Logos, forum image and rule template to choose in the wizard."""
    party_id = wizard_party.party.id
    tournament_rule_template_service.create_tournament_rule_template(
        party_id,
        't1-wizard-rules',
        'T1 Wizard Rules',
        RuleTemplateBodyFormat.markdown,
        'Be nice.',
    ).unwrap()
    return {
        'tournament_logo_url': logo_service.upload_tournament_logo_image(
            party_id, tourney_admin, png(), label='T1 Wizard Logo'
        ).unwrap(),
        'sponsor_logo_url': logo_service.upload_sponsor_logo_image(
            party_id, tourney_admin, png(), label='T1 Wizard Sponsor'
        ).unwrap(),
        'discord_forum_image_url': logo_service.upload_discord_forum_image(
            party_id, tourney_admin, png(), label='T1 Wizard Forum'
        ).unwrap(),
    }


@pytest.fixture
def filled_team_wizard(
    tourney_admin_client, wizard_party, tourney_admin, assets
):
    """Run the format, details and schedule steps for a team tournament."""
    responses = [
        post_format(
            tourney_admin_client,
            wizard_party,
            registration_mode='team_captain_managed',
            team_size='2',
            substitute_count='1',
            participant_limit='16',
            coin_cost='3',
            coin_charge_mode='captain_only',
            admin_user_ids=[str(tourney_admin.id)],
        ),
        post_details(
            tourney_admin_client,
            wizard_party,
            slug='t1-team-cup',
            title=' T1 Team Cup ',
            subtitle='Finals on stage',
            game='Counter-Strike 2',
            is_sponsored='y',
            rules_template_slug='t1-wizard-rules',
            discord_enabled='y',
            forum_channel_id='123456789012345678',
            applied_tag_ids='223456789012345678, 323456789012345678',
            event_mask=['tournament_live', 'match_completed'],
            **assets,
        ),
        post_schedule(
            tourney_admin_client,
            wizard_party,
            registration_deadline='2026-12-01T17:00',
            checkin_open_at='2026-12-01T17:15',
            checkin_close_at='2026-12-01T17:45',
        ),
    ]
    return [response.location for response in responses]


def test_start_redirects_to_format_step(tourney_admin_client, wizard_party):
    for response in [
        tourney_admin_client.get(f'{wizard_party.url}/create'),
        tourney_admin_client.post(wizard_party.url),
    ]:
        assert response.status_code == 302
        assert response.location.endswith(
            f'/for_party/{wizard_party.party.id}/create/format'
        )


def test_format_step_preselects_first_category(
    tourney_admin_client, wizard_party, tourney_admin
):
    response = tourney_admin_client.get(wizard_party.step_url('format'))

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert is_selected(body, str(wizard_party.category.id))
    assert tourney_admin.screen_name in body


def test_steps_redirect_to_the_next_step(filled_team_wizard, wizard_party):
    party_path = f'/for_party/{wizard_party.party.id}/create'
    expected = [
        f'{party_path}/{step}' for step in ['details', 'schedule', 'review']
    ]
    assert [
        location.endswith(path)
        for location, path in zip(filled_team_wizard, expected, strict=True)
    ] == [True, True, True]


def test_steps_show_stored_values_again(
    tourney_admin_client, wizard_party, filled_team_wizard
):
    pages = {
        step: tourney_admin_client.get(wizard_party.step_url(step))
        for step in ['format', 'details', 'schedule']
    }

    assert {step: page.status_code for step, page in pages.items()} == {
        'format': 200,
        'details': 200,
        'schedule': 200,
    }
    assert 'value="t1-team-cup"' in pages['details'].get_data(as_text=True)
    assert 'value="2026-12-01 18:00:00"' in pages['schedule'].get_data(
        as_text=True
    )


def test_schedule_step_suggests_party_start(tourney_admin_client, wizard_party):
    post_format(tourney_admin_client, wizard_party)
    post_details(tourney_admin_client, wizard_party)

    response = tourney_admin_client.get(wizard_party.step_url('schedule'))

    assert response.status_code == 200
    party_start = wizard_party.party.starts_at.strftime('%Y-%m-%d %H:%M:%S')
    assert f'value="{party_start}"' in response.get_data(as_text=True)


def test_review_shows_the_selection(
    tourney_admin_client, wizard_party, tourney_admin, filled_team_wizard
):
    response = tourney_admin_client.get(wizard_party.step_url('review'))

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'T1 Team Cup' in body
    assert 'T1 Main' in body
    assert 'T1 Wizard Rules' in body
    assert tourney_admin.screen_name in body


def test_review_submit_creates_team_tournament(
    tourney_admin_client,
    wizard_party,
    tourney_admin,
    assets,
    filled_team_wizard,
    pop_flashes,
):
    response = tourney_admin_client.post(wizard_party.step_url('review'))

    tournament = find_tournament(wizard_party.party.id, 't1-team-cup')
    assert response.status_code == 302
    assert response.location.endswith(
        f'/for_party/{wizard_party.party.id}/tournaments/{tournament.id}?tab=overview'
    )
    assert pop_flashes(tourney_admin_client) == [
        'Turnier „T1 Team Cup“ wurde angelegt.'
    ]
    assert tournament.title == 'T1 Team Cup'
    assert tournament.subtitle == 'Finals on stage'
    assert tournament.mode == TournamentMode.duel
    assert tournament.registration_mode == RegistrationMode.team_captain_managed
    assert tournament.team_size == 2
    assert tournament.substitute_count == 1
    assert tournament.participant_limit == 16
    assert tournament.coin_cost == 3
    assert tournament.coin_charge_mode == CoinChargeMode.captain_only
    assert tournament.category_id == wizard_party.category.id
    assert tournament.game == 'Counter-Strike 2'
    assert tournament.rules_page_slug == 't1-wizard-rules'
    assert tournament.logo_url == assets['tournament_logo_url']
    assert tournament.sponsor_logo_url == assets['sponsor_logo_url']
    assert tournament.starts_at == datetime(2026, 12, 1, 17, 0)
    assert tournament.checkin_close_at == datetime(2026, 12, 1, 16, 45)


def test_review_submit_assigns_admins_and_discord(
    tourney_admin_client,
    wizard_party,
    tourney_admin,
    assets,
    filled_team_wizard,
):
    tourney_admin_client.post(wizard_party.step_url('review'))

    tournament = find_tournament(wizard_party.party.id, 't1-team-cup')
    assert tournament_admin_service.get_tournament_admin_user_ids(
        tournament.id
    ) == {tourney_admin.id}
    assert tournament.discord_enabled
    assert tournament.discord_forum_channel_id == '123456789012345678'
    assert (
        tournament.discord_forum_image_url
        == (assets['discord_forum_image_url'])
    )
    assert tournament.discord_applied_tag_ids == [
        '223456789012345678',
        '323456789012345678',
    ]
    assert set(tournament.discord_event_mask) == {
        'tournament_live',
        'match_completed',
    }


def test_review_submit_clears_the_wizard(
    tourney_admin_client, wizard_party, filled_team_wizard
):
    tourney_admin_client.post(wizard_party.step_url('review'))

    response = tourney_admin_client.get(wizard_party.step_url('details'))

    assert response.status_code == 302
    assert response.location.endswith('/create/format')


def test_solo_tournament_ignores_team_fields(
    tourney_admin_client, wizard_party
):
    post_format(
        tourney_admin_client,
        wizard_party,
        mode='ffa',
        team_size='4',
        substitute_count='2',
        coin_charge_mode='captain_only',
    )
    post_details(tourney_admin_client, wizard_party, slug='t1-solo-ffa')
    post_schedule(
        tourney_admin_client,
        wizard_party,
        starts_at='',
        visible_on_site='',
        registration_open='',
    )

    tourney_admin_client.post(wizard_party.step_url('review'))

    tournament = find_tournament(wizard_party.party.id, 't1-solo-ffa')
    assert tournament.mode == TournamentMode.ffa
    assert tournament.registration_mode == RegistrationMode.solo
    assert tournament.team_size == 1
    assert tournament.substitute_count == 0
    # Solo registration charges the player (the "captain") only.
    assert tournament.coin_charge_mode == CoinChargeMode.captain_only
    assert tournament.starts_at is None
    assert not tournament.registration_open
    assert not tournament.discord_enabled


def test_review_submit_with_taken_slug_returns_to_review(
    tourney_admin_client, wizard_party, tourney_admin, pop_flashes
):
    tournament_service.create_tournament(
        wizard_party.party.id,
        't1-taken-slug',
        'T1 First',
        TournamentMode.duel,
        RegistrationMode.solo,
        tourney_admin,
    ).unwrap()
    pop_flashes(tourney_admin_client)
    post_format(tourney_admin_client, wizard_party)
    post_details(tourney_admin_client, wizard_party, slug='t1-taken-slug')
    post_schedule(tourney_admin_client, wizard_party)

    response = tourney_admin_client.post(wizard_party.step_url('review'))

    assert response.status_code == 302
    assert response.location.endswith('/create/review')
    assert pop_flashes(tourney_admin_client) == [
        'Dieser Slug wird bereits verwendet.'
    ]
    tournaments = tournament_service.get_tournaments_for_party(
        wizard_party.party.id
    )
    assert [t.title for t in tournaments] == ['T1 First']
