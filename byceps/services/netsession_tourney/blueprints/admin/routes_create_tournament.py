"""
byceps.services.netsession_tourney.blueprints.admin.routes_create_tournament
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create the tournament from the state of the creation wizard and set
its admins and Discord configuration (see `routes_create`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import g
from flask_babel import gettext, to_utc

from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    clear_create_wizard_state,
    deserialize_datetime_local,
    get_available_tournament_admin_users,
    parse_admin_user_ids,
)
from byceps.services.netsession_tourney.discord_service import configure_discord
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
from byceps.services.party.models import PartyID
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok, Result
from byceps.util.views import redirect_to


def _utc_or_empty(value: datetime | None) -> datetime | None:
    return value and to_utc(value)


def _int_or_default(state: dict, key: str, default: int) -> int:
    return int(state.get(key) or default)


def _coin_refund_policy(state: dict) -> CoinRefundPolicy:
    return CoinRefundPolicy(
        state.get('coin_refund_policy')
        or CoinRefundPolicy.until_tournament_end.value
    )


def _coin_charge_mode(state: dict) -> CoinChargeMode:
    return CoinChargeMode(
        state.get('coin_charge_mode') or CoinChargeMode.all_members.value
    )


def create_tournament_from_state(
    party_id: PartyID, state: dict, category_id: Any
) -> Result:
    """Create the tournament from the wizard state."""
    mode = TournamentMode(state['mode'])
    registration_mode = RegistrationMode(state['registration_mode'])
    starts_at = deserialize_datetime_local(state.get('starts_at'))
    registration_deadline = deserialize_datetime_local(
        state.get('registration_deadline')
    )
    roster_lock_at = deserialize_datetime_local(state.get('roster_lock_at'))
    checkin_open_at = deserialize_datetime_local(state.get('checkin_open_at'))
    checkin_close_at = deserialize_datetime_local(state.get('checkin_close_at'))

    return create_tournament(
        party_id,
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
        starts_at=_utc_or_empty(starts_at),
        visible_on_site=bool(state.get('visible_on_site', True)),
        registration_open=bool(state.get('registration_open', True)),
        rules_page_slug=state.get('rules_page_slug'),
        registration_deadline=_utc_or_empty(registration_deadline),
        roster_lock_at=_utc_or_empty(roster_lock_at),
        checkin_open_at=_utc_or_empty(checkin_open_at),
        checkin_close_at=_utc_or_empty(checkin_close_at),
        team_size=_int_or_default(state, 'team_size', 1),
        substitute_count=_int_or_default(state, 'substitute_count', 0),
        participant_limit=state.get('participant_limit'),
        coin_cost=_int_or_default(state, 'coin_cost', 0),
        coin_refund_policy=_coin_refund_policy(state),
        coin_charge_mode=_coin_charge_mode(state),
        category_id=category_id,
    )


def assign_wizard_admins(
    party_id: PartyID, tournament_id: Any, state: dict
) -> None:
    """Set the admins selected in the wizard; flash an error."""
    selected_admin_ids = parse_admin_user_ids(
        state.get('admin_user_ids') or [],
        {str(user.id) for user in get_available_tournament_admin_users()},
    )
    set_admin_result = set_tournament_admin_user_ids(
        party_id,
        tournament_id,
        selected_admin_ids,
        g.user.as_user(),
    )
    if set_admin_result.is_err():
        flash_error(set_admin_result.unwrap_err())


def configure_wizard_discord(
    party_id: PartyID, tournament_id: Any, state: dict
) -> None:
    """Configure Discord if enabled in the wizard; flash an error."""
    if not state.get('discord_enabled'):
        return

    discord_result = configure_discord(
        party_id,
        tournament_id,
        g.user.as_user(),
        enabled=True,
        forum_channel_id=state.get('discord_forum_channel_id'),
        discord_forum_image_url=state.get('discord_forum_image_url'),
        applied_tag_ids=state.get('discord_applied_tag_ids') or [],
        event_mask=state.get('discord_event_mask') or [],
        discord_dm_enabled=False,
        discord_dm_event_mask=[],
    )
    if discord_result.is_err():
        flash_error(discord_result.unwrap_err())


def finish_tournament_creation(
    party_id: PartyID, state: dict, result: Result
) -> Any:
    """Finish the wizard after creating the tournament; return a redirect."""
    match result:
        case Ok(tournament):
            assign_wizard_admins(party_id, tournament.id, state)
            configure_wizard_discord(party_id, tournament.id, state)
            clear_create_wizard_state(party_id)
            flash_success(
                gettext(
                    'Turnier „%(title)s“ wurde angelegt.',
                    title=tournament.title,
                )
            )
            return redirect_to(
                '.view',
                party_id=party_id,
                tournament_id=tournament.id,
                tab='overview',
            )
        case Err(message):
            flash_error(message)
            return redirect_to('.create_wizard_review', party_id=party_id)
