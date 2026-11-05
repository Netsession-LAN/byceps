"""
byceps.services.netsession_tourney.blueprints.admin.routes_overview
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask import abort, g, request
from flask_babel import gettext

from byceps.services.ticketing import ticket_category_service
from byceps.services.user import user_service
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.framework.templating import templated
from byceps.util.result import Err, Ok
from byceps.util.views import permission_required, redirect_to, respond_no_content

from ..site.views import _build_party_timetable
from ...forms import (
    BrowserPushConfigForm,
    CoinAdjustmentForm,
    CoinSettingsForm,
    DiscordDmConfigForm,
    ManagedLogoLabelForm,
    ManagedLogoUploadForm,
    SponsorLogoForm,
    SponsorLogoUploadForm,
    TournamentCategoryForm,
    TournamentPrizeForm,
    TournamentRuleTemplateForm,
)
from ...logo_service import (
    delete_discord_forum_image_asset,
    delete_sponsor_logo_asset,
    delete_tournament_logo_asset,
    get_discord_forum_image_assets,
    get_sponsor_logo_assets,
    get_tournament_logo_assets,
    set_discord_forum_image_label,
    set_sponsor_logo_label,
    set_tournament_logo_label,
    upload_discord_forum_image,
    upload_sponsor_logo_image,
    upload_tournament_logo_image,
)
from ...models import RuleTemplateBodyFormat
from ... import (
    browser_push_service,
    coin_service,
    discord_dm_outbox,
    discord_dm_service,
    participant_admin_service,
    tournament_category_service,
    tournament_prize_service,
    tournament_rule_template_service,
    tournament_service,
)
from .result_helpers import _get_party_or_404, _get_tournament_or_404, _parse_csv
from .wizard_helpers import (
    _get_discord_forum_image_asset_or_404,
    _get_sponsor_logo_asset_or_404,
    _get_ticket_user_screen_names_for_party,
    _get_tournament_category_or_404,
    _get_tournament_logo_asset_or_404,
    _get_tournament_prize_or_404,
    _get_tournament_rule_template_or_404,
)


def register(blueprint):
    @blueprint.get('/for_party/<party_id>')
    @permission_required('netsession_tourney.view')
    @templated
    def index(party_id):
        party = _get_party_or_404(party_id)
        tournaments = tournament_service.get_tournaments_for_party(party.id)
        categories = tournament_category_service.get_tournament_categories_for_party(party.id)
        categories_by_id = {category.id: category for category in categories}
        active_participant_counts_by_tournament_id = (
            participant_admin_service.get_active_participant_counts_for_tournaments(
                party.id,
                {tournament.id for tournament in tournaments},
            )
        )
        return {
            'party': party,
            'tournaments': tournaments,
            'categories_by_id': categories_by_id,
            'active_participant_counts_by_tournament_id': (
                active_participant_counts_by_tournament_id
            ),
        }


    @blueprint.get('/for_party/<party_id>/categories')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/category/index')
    def category_index(party_id):
        party = _get_party_or_404(party_id)
        categories = tournament_category_service.get_tournament_categories_for_party(party.id)
        return {
            'party': party,
            'categories': categories,
        }


    @blueprint.get('/for_party/<party_id>/timetable')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/timetable')
    def timetable(party_id):
        party = _get_party_or_404(party_id)
        selected_day_iso = (request.args.get('day') or '').strip() or None
        return {
            'party': party,
            'timetable': _build_party_timetable(
                party, selected_day_iso=selected_day_iso
            ),
        }


    @blueprint.get('/for_party/<party_id>/notifications')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/notifications/index')
    def notifications_index(party_id, erroneous_form=None):
        party = _get_party_or_404(party_id)
        browser_push_form = (
            erroneous_form
            if isinstance(erroneous_form, BrowserPushConfigForm)
            else BrowserPushConfigForm()
        )
        browser_push_config = browser_push_service.get_browser_push_config(party.id)
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
            discord_dm_form.application_id.data = discord_dm_config.application_id
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
        party = _get_party_or_404(party_id)
        form = BrowserPushConfigForm(request.form)
        if not form.validate():
            flash_error(gettext('Browser-Benachrichtigungen konnten nicht gespeichert werden.'))
            return notifications_index(party.id, form)

        match browser_push_service.configure_browser_push(
            party.id,
            enabled=bool(form.enabled.data),
        ):
            case Err(message):
                flash_error(gettext(message))
            case Ok(_config):
                flash_success(gettext('Browser-Benachrichtigungen wurden gespeichert.'))

        return redirect_to('.notifications_index', party_id=party.id)


    @blueprint.post('/for_party/<party_id>/notifications/discord-dm')
    @permission_required('netsession_tourney.manage')
    def notifications_discord_dm_update(party_id):
        party = _get_party_or_404(party_id)
        form = DiscordDmConfigForm(request.form)
        if not form.validate():
            flash_error(
                gettext(
                    'Discord-Privatbenachrichtigungen konnten nicht gespeichert werden.'
                )
            )
            return notifications_index(party.id, form)

        default_event_mask = _parse_csv(form.default_event_mask.data)

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


    @blueprint.post('/for_party/<party_id>/notifications/discord-dm/test')
    @permission_required('netsession_tourney.manage')
    def notifications_discord_dm_send_test(party_id):
        party = _get_party_or_404(party_id)

        match discord_dm_outbox.send_test_discord_dm(party.id, g.user.id):
            case Err(message):
                flash_error(gettext(message))
            case Ok(_):
                flash_success(
                    gettext('Discord-Testnachricht wurde gesendet.')
                )

        return redirect_to('.notifications_index', party_id=party.id)


    @blueprint.get('/for_party/<party_id>/coins')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/coins/index')
    def coins_index(
        party_id, erroneous_settings_form=None, erroneous_adjustment_form=None
    ):
        party = _get_party_or_404(party_id)
        settings = coin_service.get_coin_settings(party.id)
        categories = ticket_category_service.get_categories_for_party(party.id)
        category_amounts_by_id = {
            item.ticket_category_id: item.coin_amount
            for item in coin_service.get_ticket_category_coin_settings_for_party(party.id)
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
            searched_screen_name = erroneous_adjustment_form.screen_name.data.strip()
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
            coin_service.get_recent_coin_ledger_entries_for_user(party.id, selected_user.id)
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
            'suggested_screen_names': _get_ticket_user_screen_names_for_party(
                party.id
            ),
        }


    @blueprint.post('/for_party/<party_id>/coins')
    @permission_required('netsession_tourney.manage')
    def coins_update(party_id):
        party = _get_party_or_404(party_id)
        form = CoinSettingsForm(request.form)
        if not form.validate():
            flash_error(gettext('Coin-Einstellungen konnten nicht gespeichert werden.'))
            return coins_index(party.id, erroneous_settings_form=form)

        category_coin_amounts = {}
        for category in ticket_category_service.get_categories_for_party(party.id):
            raw_value = (request.form.get(f'category_coin_{category.id}') or '').strip()
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
        party = _get_party_or_404(party_id)
        form = CoinAdjustmentForm(request.form)
        if not form.validate():
            flash_error(gettext('Coin-Anpassung konnte nicht gespeichert werden.'))
            return coins_index(
                party.id,
                erroneous_adjustment_form=form,
            )

        user = user_service.find_user_by_screen_name(form.screen_name.data.strip())
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


    @blueprint.get('/for_party/<party_id>/logos/tournament')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/logo/tournament_index')
    def tournament_logo_index(party_id, erroneous_upload_form=None):
        party = _get_party_or_404(party_id)
        upload_form = (
            erroneous_upload_form
            if erroneous_upload_form is not None
            else ManagedLogoUploadForm()
        )
        return {
            'party': party,
            'logo_assets': get_tournament_logo_assets(party.id),
            'upload_form': upload_form,
            'current_logo_subtab': 'tournament',
        }


    @blueprint.post('/for_party/<party_id>/logos/tournament/upload')
    @permission_required('netsession_tourney.manage')
    def tournament_logo_upload(party_id):
        party = _get_party_or_404(party_id)
        form_data = request.form.copy()
        if request.files:
            form_data.update(request.files)
        form = ManagedLogoUploadForm(form_data)
        if not form.validate() or form.file.data is None:
            flash_error(gettext('Bitte eine Datei auswählen.'))
            return tournament_logo_index(party.id, form)

        match upload_tournament_logo_image(
            party.id,
            g.user.as_user(),
            form.file.data.stream,
            label=form.label.data,
            original_filename=form.file.data.filename,
        ):
            case Ok(_):
                flash_success(gettext('Turnierlogo wurde hochgeladen.'))
            case Err(message):
                flash_error(message)
                return tournament_logo_index(party.id, form)

        return redirect_to('.tournament_logo_index', party_id=party.id)


    @blueprint.get('/logos/tournament/<uuid:logo_asset_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/logo/tournament_update_form')
    def tournament_logo_update_form(logo_asset_id, erroneous_form=None):
        logo_asset = _get_tournament_logo_asset_or_404(logo_asset_id)
        party = _get_party_or_404(logo_asset.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else ManagedLogoLabelForm(data={'label': logo_asset.label})
        )
        return {
            'party': party,
            'logo_asset': logo_asset,
            'form': form,
            'current_logo_subtab': 'tournament',
        }


    @blueprint.post('/logos/tournament/<uuid:logo_asset_id>')
    @permission_required('netsession_tourney.manage')
    def tournament_logo_update(logo_asset_id):
        logo_asset = _get_tournament_logo_asset_or_404(logo_asset_id)
        party = _get_party_or_404(logo_asset.party_id)
        form = ManagedLogoLabelForm(request.form)
        if not form.validate():
            return tournament_logo_update_form(logo_asset.id, form)

        match set_tournament_logo_label(
            logo_asset.id, g.user.as_user(), form.label.data
        ):
            case Ok(_):
                flash_success(gettext('Turnierlogo wurde umbenannt.'))
            case Err(message):
                flash_error(message)
                return tournament_logo_update_form(logo_asset.id, form)

        return redirect_to('.tournament_logo_index', party_id=party.id)


    @blueprint.post('/logos/tournament/<uuid:logo_asset_id>/delete')
    @permission_required('netsession_tourney.manage')
    def tournament_logo_delete(logo_asset_id):
        logo_asset = _get_tournament_logo_asset_or_404(logo_asset_id)
        party = _get_party_or_404(logo_asset.party_id)

        match delete_tournament_logo_asset(logo_asset.id):
            case Ok(_):
                flash_success(gettext('Turnierlogo wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to('.tournament_logo_index', party_id=party.id)


    @blueprint.get('/for_party/<party_id>/logos/sponsor')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/logo/sponsor_index')
    def sponsor_logo_index(party_id, erroneous_upload_form=None):
        party = _get_party_or_404(party_id)
        upload_form = (
            erroneous_upload_form
            if erroneous_upload_form is not None
            else SponsorLogoUploadForm()
        )
        return {
            'party': party,
            'logo_assets': get_sponsor_logo_assets(party.id),
            'upload_form': upload_form,
            'current_logo_subtab': 'sponsor',
        }


    @blueprint.post('/for_party/<party_id>/logos/sponsor/upload')
    @permission_required('netsession_tourney.manage')
    def sponsor_logo_upload(party_id):
        party = _get_party_or_404(party_id)
        form_data = request.form.copy()
        if request.files:
            form_data.update(request.files)
        form = SponsorLogoUploadForm(form_data)
        if not form.validate() or form.file.data is None:
            flash_error(gettext('Bitte eine Datei auswählen.'))
            return sponsor_logo_index(party.id, form)

        match upload_sponsor_logo_image(
            party.id,
            g.user.as_user(),
            form.file.data.stream,
            label=form.label.data,
            target_url=form.target_url.data,
            original_filename=form.file.data.filename,
        ):
            case Ok(_):
                flash_success(gettext('Sponsor-Logo wurde hochgeladen.'))
            case Err(message):
                flash_error(message)
                return sponsor_logo_index(party.id, form)

        return redirect_to('.sponsor_logo_index', party_id=party.id)


    @blueprint.get('/logos/sponsor/<uuid:logo_asset_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/logo/sponsor_update_form')
    def sponsor_logo_update_form(logo_asset_id, erroneous_form=None):
        logo_asset = _get_sponsor_logo_asset_or_404(logo_asset_id)
        party = _get_party_or_404(logo_asset.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else SponsorLogoForm(
                data={
                    'label': logo_asset.label,
                    'target_url': logo_asset.target_url,
                }
            )
        )
        return {
            'party': party,
            'logo_asset': logo_asset,
            'form': form,
            'current_logo_subtab': 'sponsor',
        }


    @blueprint.post('/logos/sponsor/<uuid:logo_asset_id>')
    @permission_required('netsession_tourney.manage')
    def sponsor_logo_update(logo_asset_id):
        logo_asset = _get_sponsor_logo_asset_or_404(logo_asset_id)
        party = _get_party_or_404(logo_asset.party_id)
        form = SponsorLogoForm(request.form)
        if not form.validate():
            return sponsor_logo_update_form(logo_asset.id, form)

        match set_sponsor_logo_label(
            logo_asset.id,
            g.user.as_user(),
            form.label.data,
            target_url=form.target_url.data,
        ):
            case Ok(_):
                flash_success(gettext('Sponsor-Logo wurde umbenannt.'))
            case Err(message):
                flash_error(message)
                return sponsor_logo_update_form(logo_asset.id, form)

        return redirect_to('.sponsor_logo_index', party_id=party.id)


    @blueprint.post('/logos/sponsor/<uuid:logo_asset_id>/delete')
    @permission_required('netsession_tourney.manage')
    def sponsor_logo_delete(logo_asset_id):
        logo_asset = _get_sponsor_logo_asset_or_404(logo_asset_id)
        party = _get_party_or_404(logo_asset.party_id)

        match delete_sponsor_logo_asset(logo_asset.id):
            case Ok(_):
                flash_success(gettext('Sponsor-Logo wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to('.sponsor_logo_index', party_id=party.id)


    @blueprint.get('/for_party/<party_id>/logos/discord-forum')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/logo/discord_forum_index')
    def discord_forum_image_index(party_id, erroneous_upload_form=None):
        party = _get_party_or_404(party_id)
        upload_form = (
            erroneous_upload_form
            if erroneous_upload_form is not None
            else ManagedLogoUploadForm()
        )
        return {
            'party': party,
            'logo_assets': get_discord_forum_image_assets(party.id),
            'upload_form': upload_form,
            'current_logo_subtab': 'discord_forum',
        }


    @blueprint.post('/for_party/<party_id>/logos/discord-forum/upload')
    @permission_required('netsession_tourney.manage')
    def discord_forum_image_upload(party_id):
        party = _get_party_or_404(party_id)
        form_data = request.form.copy()
        if request.files:
            form_data.update(request.files)
        form = ManagedLogoUploadForm(form_data)
        if not form.validate() or form.file.data is None:
            flash_error(gettext('Bitte eine Datei auswählen.'))
            return discord_forum_image_index(party.id, form)

        match upload_discord_forum_image(
            party.id,
            g.user.as_user(),
            form.file.data.stream,
            label=form.label.data,
            original_filename=form.file.data.filename,
        ):
            case Ok(_):
                flash_success(gettext('Discord-Forum-Bild wurde hochgeladen.'))
            case Err(message):
                flash_error(message)
                return discord_forum_image_index(party.id, form)

        return redirect_to('.discord_forum_image_index', party_id=party.id)


    @blueprint.get('/logos/discord-forum/<uuid:image_asset_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/logo/discord_forum_update_form')
    def discord_forum_image_update_form(image_asset_id, erroneous_form=None):
        image_asset = _get_discord_forum_image_asset_or_404(image_asset_id)
        party = _get_party_or_404(image_asset.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else ManagedLogoLabelForm(data={'label': image_asset.label})
        )
        return {
            'party': party,
            'logo_asset': image_asset,
            'form': form,
            'current_logo_subtab': 'discord_forum',
        }


    @blueprint.post('/logos/discord-forum/<uuid:image_asset_id>')
    @permission_required('netsession_tourney.manage')
    def discord_forum_image_update(image_asset_id):
        image_asset = _get_discord_forum_image_asset_or_404(image_asset_id)
        party = _get_party_or_404(image_asset.party_id)
        form = ManagedLogoLabelForm(request.form)
        if not form.validate():
            return discord_forum_image_update_form(image_asset.id, form)

        match set_discord_forum_image_label(
            image_asset.id, g.user.as_user(), form.label.data
        ):
            case Ok(_):
                flash_success(gettext('Discord-Forum-Bild wurde umbenannt.'))
            case Err(message):
                flash_error(message)
                return discord_forum_image_update_form(image_asset.id, form)

        return redirect_to('.discord_forum_image_index', party_id=party.id)


    @blueprint.post('/logos/discord-forum/<uuid:image_asset_id>/delete')
    @permission_required('netsession_tourney.manage')
    def discord_forum_image_delete(image_asset_id):
        image_asset = _get_discord_forum_image_asset_or_404(image_asset_id)
        party = _get_party_or_404(image_asset.party_id)

        match delete_discord_forum_image_asset(image_asset.id):
            case Ok(_):
                flash_success(gettext('Discord-Forum-Bild wurde gelöscht.'))
            case Err(message):
                flash_error(message)

        return redirect_to('.discord_forum_image_index', party_id=party.id)


    @blueprint.get('/for_party/<party_id>/categories/create')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/category/create_form')
    def category_create_form(party_id, erroneous_form=None):
        party = _get_party_or_404(party_id)
        form = erroneous_form if erroneous_form else TournamentCategoryForm()
        return {
            'party': party,
            'form': form,
        }


    @blueprint.post('/for_party/<party_id>/categories')
    @permission_required('netsession_tourney.manage')
    def category_create(party_id):
        party = _get_party_or_404(party_id)
        form = TournamentCategoryForm(request.form)
        if not form.validate():
            return category_create_form(party.id, form)

        match tournament_category_service.create_tournament_category(party.id, form.title.data):
            case Ok(category):
                flash_success(
                    gettext(
                        'Kategorie "%(title)s" wurde erstellt.',
                        title=category.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return category_create_form(party.id, form)

        return redirect_to('.category_index', party_id=party.id)


    @blueprint.get('/categories/<uuid:category_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/category/update_form')
    def category_update_form(category_id, erroneous_form=None):
        category = _get_tournament_category_or_404(category_id)
        party = _get_party_or_404(category.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentCategoryForm(data={'title': category.title})
        )
        return {
            'party': party,
            'category': category,
            'form': form,
        }


    @blueprint.post('/categories/<uuid:category_id>')
    @permission_required('netsession_tourney.manage')
    def category_update(category_id):
        category = _get_tournament_category_or_404(category_id)
        party = _get_party_or_404(category.party_id)

        form = TournamentCategoryForm(request.form)
        if not form.validate():
            return category_update_form(category.id, form)

        match tournament_category_service.update_tournament_category(category.id, form.title.data):
            case Ok(updated_category):
                flash_success(
                    gettext(
                        'Kategorie "%(title)s" wurde aktualisiert.',
                        title=updated_category.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return category_update_form(category.id, form)

        return redirect_to('.category_index', party_id=party.id)


    @blueprint.post('/categories/<uuid:category_id>/up')
    @permission_required('netsession_tourney.manage')
    @respond_no_content
    def category_move_up(category_id):
        category = _get_tournament_category_or_404(category_id)

        match tournament_category_service.move_tournament_category_up(category.id):
            case Ok(_):
                flash_success(gettext('Kategorie wurde nach oben verschoben.'))
            case Err(message):
                flash_error(message)


    @blueprint.post('/categories/<uuid:category_id>/down')
    @permission_required('netsession_tourney.manage')
    @respond_no_content
    def category_move_down(category_id):
        category = _get_tournament_category_or_404(category_id)

        match tournament_category_service.move_tournament_category_down(category.id):
            case Ok(_):
                flash_success(gettext('Kategorie wurde nach unten verschoben.'))
            case Err(message):
                flash_error(message)


    @blueprint.get('/for_party/<party_id>/rules')
    @permission_required('netsession_tourney.view')
    @templated('admin/netsession_tourney/rule_template/index')
    def rule_template_index(party_id):
        party = _get_party_or_404(party_id)
        rule_templates = tournament_rule_template_service.get_tournament_rule_templates_for_party(party.id)
        return {
            'party': party,
            'rule_templates': rule_templates,
        }


    @blueprint.get('/for_party/<party_id>/rules/create')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/rule_template/create_form')
    def rule_template_create_form(party_id, erroneous_form=None):
        party = _get_party_or_404(party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentRuleTemplateForm()
        )
        return {
            'party': party,
            'form': form,
        }


    @blueprint.post('/for_party/<party_id>/rules')
    @permission_required('netsession_tourney.manage')
    def rule_template_create(party_id):
        party = _get_party_or_404(party_id)
        form = TournamentRuleTemplateForm(request.form)
        if not form.validate():
            return rule_template_create_form(party.id, form)

        match tournament_rule_template_service.create_tournament_rule_template(
            party.id,
            form.slug.data,
            form.title.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(rule_template):
                flash_success(
                    gettext(
                        'Regeltemplate "%(title)s" wurde erstellt.',
                        title=rule_template.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return rule_template_create_form(party.id, form)

        return redirect_to('.rule_template_index', party_id=party.id)


    @blueprint.get('/rules/<uuid:rule_template_id>/update')
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/rule_template/update_form')
    def rule_template_update_form(rule_template_id, erroneous_form=None):
        rule_template = _get_tournament_rule_template_or_404(rule_template_id)
        party = _get_party_or_404(rule_template.party_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentRuleTemplateForm(
                data={
                    'slug': rule_template.slug,
                    'title': rule_template.title,
                    'body_format': rule_template.body_format.value,
                    'body': rule_template.body,
                }
            )
        )
        return {
            'party': party,
            'rule_template': rule_template,
            'form': form,
        }


    @blueprint.post('/rules/<uuid:rule_template_id>')
    @permission_required('netsession_tourney.manage')
    def rule_template_update(rule_template_id):
        rule_template = _get_tournament_rule_template_or_404(rule_template_id)
        party = _get_party_or_404(rule_template.party_id)

        form = TournamentRuleTemplateForm(request.form)
        if not form.validate():
            return rule_template_update_form(rule_template.id, form)

        match tournament_rule_template_service.update_tournament_rule_template(
            rule_template.id,
            form.slug.data,
            form.title.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(updated_rule_template):
                flash_success(
                    gettext(
                        'Regeltemplate "%(title)s" wurde aktualisiert.',
                        title=updated_rule_template.title,
                    )
                )
            case Err(message):
                flash_error(message)
                return rule_template_update_form(rule_template.id, form)

        return redirect_to('.rule_template_index', party_id=party.id)


    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/create'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/prize/create_form')
    def tournament_prize_create_form(party_id, tournament_id, erroneous_form=None):
        party = _get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentPrizeForm()
        )

        return {
            'party': party,
            'tournament': tournament,
            'form': form,
        }


    @blueprint.post('/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes')
    @permission_required('netsession_tourney.manage')
    def tournament_prize_create(party_id, tournament_id):
        party = _get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        form = TournamentPrizeForm(request.form)
        if not form.validate():
            return tournament_prize_create_form(party.id, tournament.id, form)

        match tournament_prize_service.create_tournament_prize(
            tournament.id,
            form.position.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(prize):
                flash_success(
                    gettext(
                        'Preis für Platz %(position)s wurde erstellt.',
                        position=prize.position,
                    )
                )
            case Err(message):
                flash_error(message)
                return tournament_prize_create_form(party.id, tournament.id, form)

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='prizes',
        )


    @blueprint.get(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/<uuid:prize_id>/update'
    )
    @permission_required('netsession_tourney.manage')
    @templated('admin/netsession_tourney/prize/update_form')
    def tournament_prize_update_form(
        party_id, tournament_id, prize_id, erroneous_form=None
    ):
        party = _get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        prize = _get_tournament_prize_or_404(prize_id)
        if prize.tournament_id != tournament.id:
            abort(404)

        form = (
            erroneous_form
            if erroneous_form is not None
            else TournamentPrizeForm(
                data={
                    'position': prize.position,
                    'body_format': prize.body_format.value,
                    'body': prize.body,
                }
            )
        )

        return {
            'party': party,
            'tournament': tournament,
            'prize': prize,
            'form': form,
        }


    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/<uuid:prize_id>'
    )
    @permission_required('netsession_tourney.manage')
    def tournament_prize_update(party_id, tournament_id, prize_id):
        party = _get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        prize = _get_tournament_prize_or_404(prize_id)
        if prize.tournament_id != tournament.id:
            abort(404)

        form = TournamentPrizeForm(request.form)
        if not form.validate():
            return tournament_prize_update_form(
                party.id, tournament.id, prize.id, form
            )

        match tournament_prize_service.update_tournament_prize(
            prize.id,
            form.position.data,
            RuleTemplateBodyFormat(form.body_format.data),
            form.body.data,
        ):
            case Ok(updated_prize):
                flash_success(
                    gettext(
                        'Preis für Platz %(position)s wurde aktualisiert.',
                        position=updated_prize.position,
                    )
                )
            case Err(message):
                flash_error(message)
                return tournament_prize_update_form(
                    party.id, tournament.id, prize.id, form
                )

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='prizes',
        )


    @blueprint.post(
        '/for_party/<party_id>/tournaments/<uuid:tournament_id>/prizes/<uuid:prize_id>/delete'
    )
    @permission_required('netsession_tourney.manage')
    def tournament_prize_delete(party_id, tournament_id, prize_id):
        party = _get_party_or_404(party_id)
        tournament = _get_tournament_or_404(party.id, tournament_id)
        prize = _get_tournament_prize_or_404(prize_id)
        if prize.tournament_id != tournament.id:
            abort(404)

        match tournament_prize_service.delete_tournament_prize(prize.id):
            case Ok(_):
                flash_success(
                    gettext(
                        'Preis für Platz %(position)s wurde gelöscht.',
                        position=prize.position,
                    )
                )
            case Err(message):
                flash_error(message)

        return redirect_to(
            '.view',
            party_id=party.id,
            tournament_id=tournament.id,
            tab='prizes',
        )
