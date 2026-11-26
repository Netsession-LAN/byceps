"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import request
from flask_babel import gettext

from byceps.services.netsession_tourney import (
    browser_push_service,
    discord_dm_service,
    tournament_service,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_coins import (
    register_coin_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_forum_images import (
    register_discord_forum_image_edit_routes,
    register_discord_forum_image_upload_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_index import (
    register_category_create_routes,
    register_category_update_routes,
    register_notification_test_routes,
    register_overview_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_prizes import (
    register_tournament_prize_create_routes,
    register_tournament_prize_delete_routes,
    register_tournament_prize_update_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_rule_templates import (
    register_rule_template_create_routes,
    register_rule_template_update_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_sponsor_logos import (
    register_sponsor_logo_edit_routes,
    register_sponsor_logo_upload_routes,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_overview_tournament_logos import (
    register_tournament_logo_edit_routes,
    register_tournament_logo_upload_routes,
)
from byceps.services.netsession_tourney.forms import (
    BrowserPushConfigForm,
    DiscordDmConfigForm,
)
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import (
    permission_required,
    redirect_to,
)

from .result_helpers import get_party_or_404, parse_csv


def register(blueprint):
    register_overview_routes(blueprint)

    @blueprint.get('/for_party/<party_id>/notifications')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/notifications/index')
    def notifications_index(party_id, erroneous_form=None):
        party = get_party_or_404(party_id)
        browser_push_form = (
            erroneous_form
            if isinstance(erroneous_form, BrowserPushConfigForm)
            else BrowserPushConfigForm()
        )
        browser_push_config = browser_push_service.get_browser_push_config(
            party.id
        )
        if not isinstance(erroneous_form, BrowserPushConfigForm):
            browser_push_form.enabled.data = browser_push_config.enabled

        discord_dm_form = (
            erroneous_form
            if isinstance(erroneous_form, DiscordDmConfigForm)
            else DiscordDmConfigForm()
        )
        discord_dm_config = discord_dm_service.get_discord_dm_config(party.id)
        if not isinstance(erroneous_form, DiscordDmConfigForm):
            discord_dm_form.enabled.data = discord_dm_config.enabled
            discord_dm_form.application_id.data = (
                discord_dm_config.application_id
            )
            discord_dm_form.default_event_mask.data = ', '.join(
                discord_dm_config.default_event_mask
            )

        tournaments = tournament_service.get_tournaments_for_party(party.id)
        subscribed_counts_by_tournament_id = {
            tournament.id: browser_push_service.count_browser_push_subscribed_participants_for_tournament(
                party.id, tournament.id
            )
            for tournament in tournaments
        }

        return {
            'party': party,
            'browser_push_config': browser_push_config,
            'browser_push_form': browser_push_form,
            'discord_dm_config': discord_dm_config,
            'discord_dm_form': discord_dm_form,
            'discord_dm_bot_token_masked': discord_dm_service.get_masked_discord_dm_bot_token(
                party.id
            ),
            'tournaments': tournaments,
            'subscribed_counts_by_tournament_id': subscribed_counts_by_tournament_id,
        }

    @blueprint.post('/for_party/<party_id>/notifications')
    @permission_required('netsession_tourney.manage')
    def notifications_update(party_id):
        party = get_party_or_404(party_id)
        form = BrowserPushConfigForm(request.form)
        if not form.validate():
            flash_error(
                gettext(
                    'Browser-Benachrichtigungen konnten nicht gespeichert werden.'
                )
            )
            return notifications_index(party.id, form)

        match browser_push_service.configure_browser_push(
            party.id,
            enabled=bool(form.enabled.data),
        ):
            case Err(message):
                flash_error(gettext(message))
            case Ok(_config):
                flash_success(
                    gettext('Browser-Benachrichtigungen wurden gespeichert.')
                )

        return redirect_to('.notifications_index', party_id=party.id)

    @blueprint.post('/for_party/<party_id>/notifications/discord-dm')
    @permission_required('netsession_tourney.manage')
    def notifications_discord_dm_update(party_id):
        party = get_party_or_404(party_id)
        form = DiscordDmConfigForm(request.form)
        if not form.validate():
            flash_error(
                gettext(
                    'Discord-Privatbenachrichtigungen konnten nicht gespeichert werden.'
                )
            )
            return notifications_index(party.id, form)

        default_event_mask = parse_csv(form.default_event_mask.data)

        match discord_dm_service.configure_discord_dm(
            party.id,
            enabled=bool(form.enabled.data),
            application_id=form.application_id.data,
            bot_token=form.bot_token.data,
            default_event_mask=default_event_mask,
        ):
            case Err(message):
                flash_error(gettext(message))
            case Ok(_config):
                flash_success(
                    gettext(
                        'Discord-Privatbenachrichtigungen wurden gespeichert.'
                    )
                )

        return redirect_to('.notifications_index', party_id=party.id)

    register_notification_test_routes(blueprint)

    register_coin_routes(blueprint)
    register_tournament_logo_upload_routes(blueprint)
    register_tournament_logo_edit_routes(blueprint)
    register_sponsor_logo_upload_routes(blueprint)
    register_sponsor_logo_edit_routes(blueprint)
    register_discord_forum_image_upload_routes(blueprint)
    register_discord_forum_image_edit_routes(blueprint)
    register_category_create_routes(blueprint)
    register_category_update_routes(blueprint)
    register_rule_template_create_routes(blueprint)
    register_rule_template_update_routes(blueprint)
    register_tournament_prize_create_routes(blueprint)
    register_tournament_prize_update_routes(blueprint)
    register_tournament_prize_delete_routes(blueprint)
