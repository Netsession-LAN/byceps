"""
byceps.services.netsession_tourney.blueprints.admin.routes_tournament_update_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Steps of the tournament update form and its submission (see
`routes_tournament_update`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from flask import g, request
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney import (
    tournament_admin_service,
    tournament_queries,
    tournament_service,
)
from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    _get_tournament_or_404,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_form_checks import (
    get_sponsor_logo_error,
    is_invalid_tournament_logo_url,
    stripped_or_none,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_forms import (
    set_logo_choices_for_form,
    set_rules_template_choices_for_form,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    get_available_tournament_admin_users,
    parse_admin_user_ids,
    parse_category_id,
    set_category_choices_for_form,
    update_form_with_categories,
)
from byceps.services.netsession_tourney.forms import TournamentForm
from byceps.services.netsession_tourney.models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    TournamentMode,
)
from byceps.services.party.models import PartyID
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok, Result


@dataclass(frozen=True, kw_only=True)
class UpdateSelection:
    tournament_logo_url: str | None
    is_sponsored: bool
    sponsor_logo_url: str | None
    category_id: UUID


def build_update_form_data(
    tournament: Any, assigned_admin_user_ids: Any
) -> dict[str, Any]:
    """Return the form data to show the stored tournament."""
    return {
        'slug': tournament.slug,
        'title': tournament.title,
        'subtitle': tournament.subtitle,
        'tournament_logo_url': tournament.logo_url,
        'is_sponsored': tournament.is_sponsored,
        'sponsor_logo_url': tournament.sponsor_logo_url,
        'game': tournament.game,
        'category_id': str(tournament.category_id),
        'mode': tournament.mode.value,
        'registration_mode': tournament.registration_mode.value,
        'starts_at': tournament.starts_at,
        'visible_on_site': tournament.visible_on_site,
        'rules_template_slug': tournament.rules_page_slug,
        'registration_open': tournament.registration_open,
        'registration_deadline': tournament.registration_deadline,
        'roster_lock_at': tournament.roster_lock_at,
        'checkin_open_at': tournament.checkin_open_at,
        'checkin_close_at': tournament.checkin_close_at,
        'team_size': tournament.team_size or 1,
        'substitute_count': tournament.substitute_count or 0,
        'participant_limit': tournament.participant_limit,
        'coin_cost': tournament.coin_cost,
        'coin_refund_policy': tournament.coin_refund_policy.value,
        'coin_charge_mode': tournament.coin_charge_mode.value,
        'admin_user_ids': [
            str(user_id) for user_id in sorted(assigned_admin_user_ids, key=str)
        ],
    }


def set_update_form_choices(
    form: Any, party_id: PartyID, tournament: Any, available_admin_users: Any
) -> None:
    """Set the admin, logo and rules template choices of the form."""
    form.set_admin_user_choices(
        [(str(user.id), user.screen_name) for user in available_admin_users]
    )
    set_logo_choices_for_form(
        form,
        party_id,
        selected_tournament_logo_url=tournament.logo_url,
        selected_sponsor_logo_url=tournament.sponsor_logo_url,
    )
    set_rules_template_choices_for_form(
        form,
        party_id,
        selected_slug=tournament.rules_page_slug,
    )


def build_update_form_context(
    party: Any, tournament_id: Any, erroneous_form: Any
) -> dict[str, Any]:
    """Return the template context of the tournament update form."""
    tournament = _get_tournament_or_404(party.id, tournament_id)
    available_admin_users = get_available_tournament_admin_users()
    assigned_admin_user_ids = (
        tournament_admin_service.get_tournament_admin_user_ids(tournament.id)
    )

    if erroneous_form:
        form = update_form_with_categories(
            party.id,
            category_id=tournament.category_id,
            erroneous_form=erroneous_form,
        )
    else:
        data = build_update_form_data(tournament, assigned_admin_user_ids)
        form = update_form_with_categories(
            party.id,
            category_id=tournament.category_id,
            erroneous_form=TournamentForm(data=data),
        )
        form.registration_mode.data = tournament.registration_mode.value
        form.mode.data = tournament.mode.value
        form.category_id.data = str(tournament.category_id)
    set_update_form_choices(form, party.id, tournament, available_admin_users)

    return {
        'party': party,
        'tournament': tournament,
        'stages': tournament_queries.get_stages_for_tournament(
            party.id, tournament.id
        ),
        'form': form,
    }


def build_submitted_update_form(
    party_id: PartyID, tournament: Any
) -> tuple[TournamentForm, set[str]]:
    """Build the submitted form and the IDs of the available admins."""
    form = TournamentForm(request.form)
    set_category_choices_for_form(form, party_id)
    available_admin_users = get_available_tournament_admin_users()
    available_admin_user_ids = {str(user.id) for user in available_admin_users}
    set_update_form_choices(form, party_id, tournament, available_admin_users)
    return form, available_admin_user_ids


def parse_update_selection(
    party_id: PartyID, form: TournamentForm
) -> UpdateSelection | None:
    """Check logos and category; flash the error and return `None`."""
    tournament_logo_url = stripped_or_none(form.tournament_logo_url.data)
    if is_invalid_tournament_logo_url(party_id, tournament_logo_url):
        flash_error(gettext('Ungültiges Turnierlogo ausgewählt.'))
        return None

    is_sponsored = bool(form.is_sponsored.data)
    sponsor_logo_url = stripped_or_none(form.sponsor_logo_url.data)
    sponsor_logo_error = get_sponsor_logo_error(
        party_id, is_sponsored, sponsor_logo_url
    )
    if sponsor_logo_error is not None:
        flash_error(sponsor_logo_error)
        return None

    category_id = parse_category_id(form.category_id.data)
    if category_id is None:
        flash_error(gettext('Bitte eine gültige Kategorie auswählen.'))
        return None

    return UpdateSelection(
        tournament_logo_url=tournament_logo_url,
        is_sponsored=is_sponsored,
        sponsor_logo_url=sponsor_logo_url,
        category_id=category_id,
    )


def _utc_or_empty(value: datetime | None) -> datetime | None:
    return value and to_utc(value)


def _is_solo(form: TournamentForm) -> bool:
    return form.registration_mode.data == RegistrationMode.solo.value


def _team_size(form: TournamentForm) -> Any:
    return 1 if _is_solo(form) else form.team_size.data


def _substitute_count(form: TournamentForm) -> Any:
    return 0 if _is_solo(form) else form.substitute_count.data


def _coin_charge_mode(form: TournamentForm) -> CoinChargeMode:
    return CoinChargeMode(
        CoinChargeMode.all_members.value
        if _is_solo(form)
        else form.coin_charge_mode.data
    )


def update_tournament_from_form(
    party_id: PartyID,
    tournament_id: Any,
    form: TournamentForm,
    selection: UpdateSelection,
) -> Result:
    """Store the submitted tournament data."""
    return tournament_service.update_tournament(
        party_id,
        tournament_id,
        g.user.as_user(),
        mode=TournamentMode(form.mode.data),
        registration_mode=RegistrationMode(form.registration_mode.data),
        title=form.title.data,
        subtitle=form.subtitle.data,
        logo_url=selection.tournament_logo_url,
        is_sponsored=selection.is_sponsored,
        sponsor_logo_url=selection.sponsor_logo_url,
        game=form.game.data,
        starts_at=_utc_or_empty(form.starts_at.data),
        visible_on_site=bool(form.visible_on_site.data),
        rules_page_slug=form.rules_template_slug.data,
        registration_open=bool(form.registration_open.data),
        registration_deadline=_utc_or_empty(form.registration_deadline.data),
        roster_lock_at=_utc_or_empty(form.roster_lock_at.data),
        checkin_open_at=_utc_or_empty(form.checkin_open_at.data),
        checkin_close_at=_utc_or_empty(form.checkin_close_at.data),
        team_size=_team_size(form),
        substitute_count=_substitute_count(form),
        participant_limit=form.participant_limit.data,
        coin_cost=form.coin_cost.data,
        coin_refund_policy=CoinRefundPolicy(form.coin_refund_policy.data),
        coin_charge_mode=_coin_charge_mode(form),
        category_id=selection.category_id,
    )


def _finish_tournament_update(
    party_id: PartyID,
    tournament_id: Any,
    form: TournamentForm,
    available_admin_user_ids: set[str],
    mode_changed: bool,
    registration_mode_changed: bool,
) -> None:
    """Store the admins and flash the success messages."""
    selected_admin_user_ids = parse_admin_user_ids(
        form.admin_user_ids.data, available_admin_user_ids
    )
    set_admin_result = tournament_admin_service.set_tournament_admin_user_ids(
        party_id,
        tournament_id,
        selected_admin_user_ids,
        g.user.as_user(),
    )
    if set_admin_result.is_err():
        flash_error(set_admin_result.unwrap_err())

    flash_success(gettext('Turnier wurde gespeichert.'))
    if mode_changed:
        flash_success(gettext('Modus geändert, alte Phasen wurden gelöscht.'))
    if registration_mode_changed:
        flash_success(gettext('Anmeldemodus wurde geändert.'))


def handle_update_result(
    result: Result,
    party_id: PartyID,
    tournament_id: Any,
    form: TournamentForm,
    available_admin_user_ids: set[str],
    mode_changed: bool,
    registration_mode_changed: bool,
) -> bool:
    """Finish a successful update; flash the error and return false."""
    match result:
        case Ok(_):
            _finish_tournament_update(
                party_id,
                tournament_id,
                form,
                available_admin_user_ids,
                mode_changed,
                registration_mode_changed,
            )
        case Err(message):
            flash_error(message)
            return False

    return True
