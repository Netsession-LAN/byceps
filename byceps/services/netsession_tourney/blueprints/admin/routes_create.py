"""
byceps.services.netsession_tourney.blueprints.admin.routes_create
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney.blueprints.admin.routes_create_steps import (
    register_create_review_routes,
    register_create_schedule_routes,
    register_create_start_routes,
)
from byceps.services.netsession_tourney.discord_service import configure_discord
from byceps.services.netsession_tourney.forms import (
    TournamentWizardDetailsForm,
)
from byceps.services.netsession_tourney.logo_service import (
    is_known_discord_forum_image_url,
    is_known_sponsor_logo_url,
    is_known_tournament_logo_url,
)
from byceps.services.netsession_tourney.models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    TournamentMode,
)
from byceps.services.netsession_tourney.tournament_admin_service import (
    set_tournament_admin_user_ids,
)
from byceps.services.netsession_tourney.tournament_service import (
    create_tournament,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from .result_helpers import get_party_or_404, parse_csv
from .wizard_forms import (
    build_wizard_details_form,
)
from .wizard_helpers import (
    assert_party_has_categories_or_redirect,
    clear_create_wizard_state,
    deserialize_datetime_local,
    get_available_tournament_admin_users,
    get_create_wizard_state,
    is_wizard_details_complete,
    is_wizard_format_complete,
    is_wizard_schedule_complete,
    parse_admin_user_ids,
    parse_category_id,
    set_create_wizard_state,
    slugify_tournament_title,
)


def register(blueprint):
    register_create_start_routes(blueprint)

    @blueprint.get('/for_party/<party_id>/create/details')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/details')
    def create_wizard_details(party_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)

        form = build_wizard_details_form(
            party.id,
            state=state,
            erroneous_form=erroneous_form,
        )

        return {
            'party': party,
            'form': form,
            'wizard_step': 'details',
        }

    @blueprint.post('/for_party/<party_id>/create/details')
    @permission_required('netsession_tourney.manage')
    def create_wizard_details_submit(party_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)

        form = build_wizard_details_form(
            party.id,
            state=state,
            erroneous_form=TournamentWizardDetailsForm(request.form),
        )
        if not form.validate():
            return create_wizard_details(party.id, form)

        tournament_logo_url = (
            form.tournament_logo_url.data.strip()
            if form.tournament_logo_url.data
            else None
        )
        if tournament_logo_url and not is_known_tournament_logo_url(
            party.id, tournament_logo_url
        ):
            flash_error(gettext('Ungültiges Turnierlogo ausgewählt.'))
            return create_wizard_details(party.id, form)

        is_sponsored = bool(form.is_sponsored.data)
        sponsor_logo_url = (
            form.sponsor_logo_url.data.strip()
            if form.sponsor_logo_url.data
            else None
        )
        if is_sponsored and not sponsor_logo_url:
            flash_error(gettext('Bitte ein Sponsor-Logo auswählen.'))
            return create_wizard_details(party.id, form)
        if sponsor_logo_url and not is_known_sponsor_logo_url(
            party.id, sponsor_logo_url
        ):
            flash_error(gettext('Ungültiges Sponsor-Logo ausgewählt.'))
            return create_wizard_details(party.id, form)

        discord_enabled = bool(form.discord_enabled.data)
        discord_forum_image_url = (
            form.discord_forum_image_url.data.strip()
            if form.discord_forum_image_url.data
            else None
        )
        if discord_forum_image_url and not is_known_discord_forum_image_url(
            party.id, discord_forum_image_url
        ):
            flash_error(
                gettext('Das ausgewählte Discord-Forum-Bild ist ungültig.')
            )
            return create_wizard_details(party.id, form)

        discord_event_mask = list(form.event_mask.data or [])
        if discord_enabled and not (form.forum_channel_id.data or '').strip():
            flash_error(gettext('Bitte eine Discord-Forum-Channel-ID angeben.'))
            return create_wizard_details(party.id, form)
        if discord_enabled and not discord_event_mask:
            flash_error(
                gettext('Bitte mindestens ein Discord-Forum-Event auswählen.')
            )
            return create_wizard_details(party.id, form)

        slug = form.slug.data.strip()
        if not slug:
            slug = slugify_tournament_title(form.title.data)

        state.update(
            {
                'slug': slug,
                'title': form.title.data.strip(),
                'subtitle': form.subtitle.data.strip()
                if form.subtitle.data
                else None,
                'logo_url': tournament_logo_url,
                'is_sponsored': is_sponsored,
                'sponsor_logo_url': sponsor_logo_url if is_sponsored else None,
                'game': form.game.data.strip() if form.game.data else None,
                'rules_page_slug': form.rules_template_slug.data.strip()
                if form.rules_template_slug.data
                else None,
                'discord_enabled': discord_enabled,
                'discord_forum_channel_id': form.forum_channel_id.data.strip()
                if form.forum_channel_id.data
                else None,
                'discord_forum_image_url': discord_forum_image_url,
                'discord_applied_tag_ids': parse_csv(form.applied_tag_ids.data),
                'discord_event_mask': discord_event_mask,
            }
        )
        set_create_wizard_state(party.id, state)

        return redirect_to('.create_wizard_schedule', party_id=party.id)

    register_create_schedule_routes(blueprint)
    register_create_review_routes(blueprint)

    @blueprint.post('/for_party/<party_id>/create/review')
    @permission_required('netsession_tourney.manage')
    def create_wizard_review_submit(party_id):
        party = get_party_or_404(party_id)
        redirect_response = assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = get_create_wizard_state(party.id)
        if not is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)
        if not is_wizard_schedule_complete(state):
            return redirect_to('.create_wizard_schedule', party_id=party.id)

        category_id = parse_category_id(state.get('category_id'))
        if category_id is None:
            flash_error(gettext('Bitte eine gültige Kategorie auswählen.'))
            return redirect_to('.create_wizard_format', party_id=party.id)

        mode = TournamentMode(state['mode'])
        registration_mode = RegistrationMode(state['registration_mode'])
        starts_at = deserialize_datetime_local(state.get('starts_at'))
        registration_deadline = deserialize_datetime_local(
            state.get('registration_deadline')
        )
        roster_lock_at = deserialize_datetime_local(state.get('roster_lock_at'))
        checkin_open_at = deserialize_datetime_local(
            state.get('checkin_open_at')
        )
        checkin_close_at = deserialize_datetime_local(
            state.get('checkin_close_at')
        )

        result = create_tournament(
            party.id,
            state['slug'],
            state['title'],
            mode,
            registration_mode,
            g.user.as_user(),
            subtitle=state.get('subtitle'),
            logo_url=state.get('logo_url'),
            is_sponsored=bool(state.get('is_sponsored')),
            sponsor_logo_url=state.get('sponsor_logo_url'),
            game=state.get('game'),
            starts_at=starts_at and to_utc(starts_at),
            visible_on_site=bool(state.get('visible_on_site', True)),
            registration_open=bool(state.get('registration_open', True)),
            rules_page_slug=state.get('rules_page_slug'),
            registration_deadline=registration_deadline
            and to_utc(registration_deadline),
            roster_lock_at=roster_lock_at and to_utc(roster_lock_at),
            checkin_open_at=checkin_open_at and to_utc(checkin_open_at),
            checkin_close_at=checkin_close_at and to_utc(checkin_close_at),
            team_size=int(state.get('team_size') or 1),
            substitute_count=int(state.get('substitute_count') or 0),
            participant_limit=state.get('participant_limit'),
            coin_cost=int(state.get('coin_cost') or 0),
            coin_refund_policy=CoinRefundPolicy(
                state.get('coin_refund_policy')
                or CoinRefundPolicy.until_tournament_end.value
            ),
            coin_charge_mode=CoinChargeMode(
                state.get('coin_charge_mode')
                or CoinChargeMode.all_members.value
            ),
            category_id=category_id,
        )

        match result:
            case Ok(tournament):
                selected_admin_ids = parse_admin_user_ids(
                    state.get('admin_user_ids') or [],
                    {
                        str(user.id)
                        for user in get_available_tournament_admin_users()
                    },
                )
                set_admin_result = set_tournament_admin_user_ids(
                    party.id,
                    tournament.id,
                    selected_admin_ids,
                    g.user.as_user(),
                )
                if set_admin_result.is_err():
                    flash_error(set_admin_result.unwrap_err())

                if state.get('discord_enabled'):
                    discord_result = configure_discord(
                        party.id,
                        tournament.id,
                        g.user.as_user(),
                        enabled=True,
                        forum_channel_id=state.get('discord_forum_channel_id'),
                        discord_forum_image_url=state.get(
                            'discord_forum_image_url'
                        ),
                        applied_tag_ids=state.get('discord_applied_tag_ids')
                        or [],
                        event_mask=state.get('discord_event_mask') or [],
                        discord_dm_enabled=False,
                        discord_dm_event_mask=[],
                    )
                    if discord_result.is_err():
                        flash_error(discord_result.unwrap_err())

                clear_create_wizard_state(party.id)
                flash_success(
                    gettext(
                        'Turnier „%(title)s“ wurde angelegt.',
                        title=tournament.title,
                    )
                )
                return redirect_to(
                    '.view',
                    party_id=party.id,
                    tournament_id=tournament.id,
                    tab='overview',
                )
            case Err(message):
                flash_error(message)
                return redirect_to('.create_wizard_review', party_id=party.id)
