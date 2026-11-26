"""
byceps.services.netsession_tourney.blueprints.admin.wizard_form_data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Initial data of the tournament wizard's format form (see
`wizard_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.models import (
    CoinChargeMode,
    CoinRefundPolicy,
    RegistrationMode,
    TournamentMode,
)


def build_wizard_format_form_data(state: dict) -> dict:
    return {
        **_build_wizard_format_registration_data(state),
        **_build_wizard_format_coin_data(state),
    }


def _build_wizard_format_registration_data(state: dict) -> dict:
    return {
        'category_id': state.get('category_id'),
        'mode': state.get('mode') or TournamentMode.duel.value,
        'registration_mode': state.get('registration_mode')
        or RegistrationMode.solo.value,
        'team_size': state.get('team_size') or 1,
        'substitute_count': state.get('substitute_count') or 0,
        'participant_limit': state.get('participant_limit'),
    }


def _build_wizard_format_coin_data(state: dict) -> dict:
    return {
        'coin_cost': state.get('coin_cost', 0),
        'coin_refund_policy': state.get('coin_refund_policy')
        or CoinRefundPolicy.until_tournament_end.value,
        'coin_charge_mode': state.get('coin_charge_mode')
        or CoinChargeMode.all_members.value,
        'admin_user_ids': state.get('admin_user_ids') or [],
    }
