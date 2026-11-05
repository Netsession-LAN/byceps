"""
byceps.services.netsession_tourney.blueprints.admin.routes_create
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from uuid import UUID

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to

from ...forms import (
    TournamentWizardDetailsForm,
    TournamentWizardFormatForm,
    TournamentWizardScheduleForm,
)
from ...logo_service import (
    is_known_discord_forum_image_url,
    is_known_sponsor_logo_url,
    is_known_tournament_logo_url,
)
from ...models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    TournamentMode,
)
from ...discord_service import configure_discord
from ...tournament_admin_service import set_tournament_admin_user_ids
from ...tournament_category_service import get_tournament_categories_for_party
from ...tournament_rule_template_service import (
    get_tournament_rule_templates_for_party,
)
from ...tournament_service import create_tournament
from .result_helpers import _get_party_or_404, _parse_csv
from .wizard_helpers import (
    _assert_party_has_categories_or_redirect,
    _build_wizard_details_form,
    _build_wizard_format_form,
    _build_wizard_schedule_form,
    _clear_create_wizard_state,
    _deserialize_datetime_local,
    _get_available_tournament_admin_users,
    _get_create_wizard_state,
    _is_wizard_details_complete,
    _is_wizard_format_complete,
    _is_wizard_schedule_complete,
    _parse_admin_user_ids,
    _parse_category_id,
    _serialize_datetime_local,
    _set_create_wizard_state,
    _slugify_tournament_title,
)


def register(blueprint):
    @blueprint.get('/for_party/<party_id>/create')
    @permission_required('netsession_tourney.manage')
    def create_form(party_id):
        return redirect_to('.create_wizard_format', party_id=party_id)


    @blueprint.post('/for_party/<party_id>')
    @permission_required('netsession_tourney.manage')
    def create(party_id):
        return redirect_to('.create_wizard_format', party_id=party_id)


    @blueprint.get('/for_party/<party_id>/create/format')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/format')
    def create_wizard_format(party_id, erroneous_form=None):
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        form, _ = _build_wizard_format_form(
            party.id,
            state=state,
            erroneous_form=erroneous_form,
        )

        return {
            'party': party,
            'form': form,
            'wizard_step': 'format',
        }


    @blueprint.post('/for_party/<party_id>/create/format')
    @permission_required('netsession_tourney.manage')
    def create_wizard_format_submit(party_id):
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        form, available_admin_user_ids = _build_wizard_format_form(
            party.id,
            state=state,
            erroneous_form=TournamentWizardFormatForm(request.form),
        )
        if not form.validate():
            return create_wizard_format(party.id, form)

        selected_admin_user_ids = _parse_admin_user_ids(
            form.admin_user_ids.data, available_admin_user_ids
        )
        registration_mode = RegistrationMode(form.registration_mode.data)

        state.update(
            {
                'category_id': form.category_id.data,
                'mode': form.mode.data,
                'registration_mode': form.registration_mode.data,
                'team_size': 1
                if registration_mode == RegistrationMode.solo
                else form.team_size.data,
                'substitute_count': 0
                if registration_mode == RegistrationMode.solo
                else form.substitute_count.data,
                'participant_limit': form.participant_limit.data,
                'coin_cost': form.coin_cost.data,
                'coin_refund_policy': form.coin_refund_policy.data,
                'coin_charge_mode': CoinChargeMode.all_members.value
                if registration_mode == RegistrationMode.solo
                else form.coin_charge_mode.data,
                'admin_user_ids': [str(user_id) for user_id in selected_admin_user_ids],
            }
        )
        _set_create_wizard_state(party.id, state)

        return redirect_to('.create_wizard_details', party_id=party.id)


    @blueprint.get('/for_party/<party_id>/create/details')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/details')
    def create_wizard_details(party_id, erroneous_form=None):
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        if not _is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)

        form = _build_wizard_details_form(
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
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        if not _is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)

        form = _build_wizard_details_form(
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
        if (
            tournament_logo_url
            and not is_known_tournament_logo_url(party.id, tournament_logo_url)
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
        if (
            discord_forum_image_url
            and not is_known_discord_forum_image_url(
                party.id, discord_forum_image_url
            )
        ):
            flash_error(gettext('Das ausgewählte Discord-Forum-Bild ist ungültig.'))
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
            slug = _slugify_tournament_title(form.title.data)

        state.update(
            {
                'slug': slug,
                'title': form.title.data.strip(),
                'subtitle': form.subtitle.data.strip() if form.subtitle.data else None,
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
                'discord_applied_tag_ids': _parse_csv(form.applied_tag_ids.data),
                'discord_event_mask': discord_event_mask,
            }
        )
        _set_create_wizard_state(party.id, state)

        return redirect_to('.create_wizard_schedule', party_id=party.id)


    @blueprint.get('/for_party/<party_id>/create/schedule')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/schedule')
    def create_wizard_schedule(party_id, erroneous_form=None):
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        if not _is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not _is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)

        form = _build_wizard_schedule_form(
            party=party,
            state=state,
            erroneous_form=erroneous_form,
        )

        return {
            'party': party,
            'form': form,
            'wizard_step': 'schedule',
        }


    @blueprint.post('/for_party/<party_id>/create/schedule')
    @permission_required('netsession_tourney.manage')
    def create_wizard_schedule_submit(party_id):
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        if not _is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not _is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)

        form = TournamentWizardScheduleForm(request.form)
        if not form.validate():
            return create_wizard_schedule(party.id, form)

        state.update(
            {
                'starts_at': _serialize_datetime_local(form.starts_at.data),
                'visible_on_site': bool(form.visible_on_site.data),
                'registration_open': bool(form.registration_open.data),
                'registration_deadline': _serialize_datetime_local(
                    form.registration_deadline.data
                ),
                'roster_lock_at': _serialize_datetime_local(form.roster_lock_at.data),
                'checkin_open_at': _serialize_datetime_local(form.checkin_open_at.data),
                'checkin_close_at': _serialize_datetime_local(
                    form.checkin_close_at.data
                ),
            }
        )
        _set_create_wizard_state(party.id, state)

        return redirect_to('.create_wizard_review', party_id=party.id)


    @blueprint.get('/for_party/<party_id>/create/review')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/wizard/review')
    def create_wizard_review(party_id):
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        if not _is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not _is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)
        if not _is_wizard_schedule_complete(state):
            return redirect_to('.create_wizard_schedule', party_id=party.id)

        categories_by_id = {
            str(category.id): category
            for category in get_tournament_categories_for_party(party.id)
        }
        selected_admin_ids: set[UserID] = set()
        for raw_user_id in state.get('admin_user_ids', []):
            if not raw_user_id:
                continue

            try:
                selected_admin_ids.add(UserID(UUID(raw_user_id)))
            except ValueError:
                continue
        selected_admin_users = sorted(
            user_service.get_users(selected_admin_ids),
            key=lambda user: user.screen_name.lower(),
        )
        rule_templates_by_slug = {
            template.slug: template
            for template in get_tournament_rule_templates_for_party(party.id)
        }
        selected_rules_template = rule_templates_by_slug.get(
            state.get('rules_page_slug')
        )

        return {
            'party': party,
            'state': state,
            'selected_category': categories_by_id.get(state.get('category_id')),
            'selected_admin_users': selected_admin_users,
            'selected_rules_template': selected_rules_template,
            'wizard_step': 'review',
        }


    @blueprint.post('/for_party/<party_id>/create/review')
    @permission_required('netsession_tourney.manage')
    def create_wizard_review_submit(party_id):
        party = _get_party_or_404(party_id)
        redirect_response = _assert_party_has_categories_or_redirect(party)
        if redirect_response is not None:
            return redirect_response

        state = _get_create_wizard_state(party.id)
        if not _is_wizard_format_complete(state):
            return redirect_to('.create_wizard_format', party_id=party.id)
        if not _is_wizard_details_complete(state):
            return redirect_to('.create_wizard_details', party_id=party.id)
        if not _is_wizard_schedule_complete(state):
            return redirect_to('.create_wizard_schedule', party_id=party.id)

        category_id = _parse_category_id(state.get('category_id'))
        if category_id is None:
            flash_error(gettext('Bitte eine gültige Kategorie auswählen.'))
            return redirect_to('.create_wizard_format', party_id=party.id)

        mode = TournamentMode(state['mode'])
        registration_mode = RegistrationMode(state['registration_mode'])
        starts_at = _deserialize_datetime_local(state.get('starts_at'))
        registration_deadline = _deserialize_datetime_local(
            state.get('registration_deadline')
        )
        roster_lock_at = _deserialize_datetime_local(state.get('roster_lock_at'))
        checkin_open_at = _deserialize_datetime_local(state.get('checkin_open_at'))
        checkin_close_at = _deserialize_datetime_local(state.get('checkin_close_at'))

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
                selected_admin_ids = _parse_admin_user_ids(
                    state.get('admin_user_ids') or [],
                    {str(user.id) for user in _get_available_tournament_admin_users()},
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
                        applied_tag_ids=state.get('discord_applied_tag_ids') or [],
                        event_mask=state.get('discord_event_mask') or [],
                        discord_dm_enabled=False,
                        discord_dm_event_mask=[],
                    )
                    if discord_result.is_err():
                        flash_error(discord_result.unwrap_err())

                _clear_create_wizard_state(party.id)
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
