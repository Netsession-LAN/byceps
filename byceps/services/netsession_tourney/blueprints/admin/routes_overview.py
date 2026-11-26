"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney import (
    browser_push_service,
    coin_service,
    discord_dm_service,
    tournament_service,
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
    CoinAdjustmentForm,
    CoinSettingsForm,
    DiscordDmConfigForm,
)
from byceps.services.netsession_tourney.screen_name_suggestions import (
    get_suggested_screen_names_for_party,
)
from byceps.services.ticketing import ticket_category_service
from byceps.services.user import user_service
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

    @blueprint.get('/for_party/<party_id>/coins')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/coins/index')
    def coins_index(
        party_id, erroneous_settings_form=None, erroneous_adjustment_form=None
    ):
        party = get_party_or_404(party_id)
        settings = coin_service.get_coin_settings(party.id)
        categories = ticket_category_service.get_categories_for_party(party.id)
        category_amounts_by_id = {
            item.ticket_category_id: item.coin_amount
            for item in coin_service.get_ticket_category_coin_settings_for_party(
                party.id
            )
        }

        settings_form = (
            erroneous_settings_form
            if erroneous_settings_form is not None
            else CoinSettingsForm(
                data={
                    'enabled': settings.enabled,
                    'default_coin_amount': settings.default_coin_amount,
                }
            )
        )

        searched_screen_name = (request.args.get('screen_name') or '').strip()
        if (
            not searched_screen_name
            and erroneous_adjustment_form is not None
            and erroneous_adjustment_form.screen_name.data
        ):
            searched_screen_name = (
                erroneous_adjustment_form.screen_name.data.strip()
            )
        selected_user = (
            user_service.find_user_by_screen_name(searched_screen_name)
            if searched_screen_name
            else None
        )
        selected_user_balance = (
            coin_service.get_user_coin_balance(party.id, selected_user.id)
            if selected_user is not None
            else None
        )
        recent_coin_entries = (
            coin_service.get_recent_coin_ledger_entries_for_user(
                party.id, selected_user.id
            )
            if selected_user is not None
            else []
        )

        adjustment_form = (
            erroneous_adjustment_form
            if erroneous_adjustment_form is not None
            else CoinAdjustmentForm(
                data={'screen_name': searched_screen_name}
                if searched_screen_name
                else None
            )
        )

        return {
            'party': party,
            'settings': settings,
            'settings_form': settings_form,
            'ticket_categories': categories,
            'category_amounts_by_id': category_amounts_by_id,
            'adjustment_form': adjustment_form,
            'searched_screen_name': searched_screen_name,
            'selected_user': selected_user,
            'selected_user_balance': selected_user_balance,
            'recent_coin_entries': recent_coin_entries,
            'suggested_screen_names': get_suggested_screen_names_for_party(
                party.id
            ),
        }

    @blueprint.post('/for_party/<party_id>/coins')
    @permission_required('netsession_tourney.manage')
    def coins_update(party_id):
        party = get_party_or_404(party_id)
        form = CoinSettingsForm(request.form)
        if not form.validate():
            flash_error(
                gettext('Coin-Einstellungen konnten nicht gespeichert werden.')
            )
            return coins_index(party.id, erroneous_settings_form=form)

        category_coin_amounts = {}
        for category in ticket_category_service.get_categories_for_party(
            party.id
        ):
            raw_value = (
                request.form.get(f'category_coin_{category.id}') or ''
            ).strip()
            if not raw_value:
                continue

            try:
                amount = int(raw_value)
            except ValueError:
                flash_error(
                    gettext(
                        'Für die Ticket-Kategorie "%(title)s" ist kein gültiger Coin-Wert eingetragen.',
                        title=category.title,
                    )
                )
                return coins_index(party.id, erroneous_settings_form=form)

            if amount < 0:
                flash_error(
                    gettext(
                        'Für die Ticket-Kategorie "%(title)s" muss der Coin-Wert 0 oder größer sein.',
                        title=category.title,
                    )
                )
                return coins_index(party.id, erroneous_settings_form=form)

            category_coin_amounts[category.id] = amount

        match coin_service.configure_coin_settings(
            party.id,
            g.user.as_user(),
            enabled=bool(form.enabled.data),
            default_coin_amount=form.default_coin_amount.data,
            ticket_category_coin_amounts=category_coin_amounts,
        ):
            case Ok(_settings):
                flash_success(gettext('Coin-Einstellungen wurden gespeichert.'))
            case Err(message):
                flash_error(gettext(message))
                return coins_index(party.id, erroneous_settings_form=form)

        return redirect_to('.coins_index', party_id=party.id)

    @blueprint.post('/for_party/<party_id>/coins/adjust')
    @permission_required('netsession_tourney.manage')
    def coins_adjust(party_id):
        party = get_party_or_404(party_id)
        form = CoinAdjustmentForm(request.form)
        if not form.validate():
            flash_error(
                gettext('Coin-Anpassung konnte nicht gespeichert werden.')
            )
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        user = user_service.find_user_by_screen_name(
            form.screen_name.data.strip()
        )
        if user is None:
            flash_error(gettext('Der angegebene User wurde nicht gefunden.'))
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        plus_amount = form.plus_amount.data or 0
        minus_amount = form.minus_amount.data or 0

        if plus_amount and minus_amount:
            flash_error(
                gettext(
                    'Bitte nur Plus-Coins oder Minus-Coins eintragen, nicht beides gleichzeitig.'
                )
            )
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        if not plus_amount and not minus_amount:
            flash_error(
                gettext(
                    'Bitte einen Wert bei Plus-Coins oder Minus-Coins eintragen.'
                )
            )
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        amount_delta = plus_amount if plus_amount else -minus_amount

        match coin_service.adjust_user_coins(
            party.id,
            user.id,
            amount_delta,
            form.note.data or '',
            g.user.as_user(),
        ):
            case Ok(_balance):
                flash_success(
                    gettext(
                        'Die Coins für "%(screen_name)s" wurden angepasst.',
                        screen_name=user.screen_name,
                    )
                )
            case Err(message):
                flash_error(gettext(message))
                return coins_index(
                    party.id,
                    erroneous_adjustment_form=form,
                )

        return redirect_to(
            '.coins_index',
            party_id=party.id,
            screen_name=user.screen_name,
        )

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
