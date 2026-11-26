"""
byceps.services.netsession_tourney.blueprints.admin.wizard_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from datetime import datetime
import re
import unicodedata
from uuid import UUID

from flask import session
from flask_babel import gettext

from byceps.services.authz import authz_service
from byceps.services.netsession_tourney.forms import (
    TournamentForm,
    TournamentWizardFormatForm,
)
from byceps.services.netsession_tourney.models import (
    TournamentCategoryID,
)
from byceps.services.netsession_tourney.tournament_category_service import (
    get_tournament_categories_for_party,
)
from byceps.services.party.models import Party
from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.framework.flash import flash_error
from byceps.util.views import redirect_to

from .route_config import (
    CREATE_WIZARD_SESSION_KEY,
    STAGE_BUILDER_WIZARD_SESSION_KEY,
)


def set_category_choices_for_form(
    form: TournamentForm | TournamentWizardFormatForm, party_id: str
) -> None:
    categories = get_tournament_categories_for_party(party_id)
    form.set_category_choices(
        [(str(category.id), category.title) for category in categories]
    )


def parse_category_id(
    raw_category_id: str | None,
) -> TournamentCategoryID | None:
    if not raw_category_id:
        return None

    try:
        return TournamentCategoryID(UUID(raw_category_id))
    except ValueError:
        return None


def update_form_with_categories(
    party_id: str,
    *,
    category_id: TournamentCategoryID,
    erroneous_form=None,
):
    form = erroneous_form if erroneous_form else TournamentForm()
    set_category_choices_for_form(form, party_id)
    if erroneous_form is None:
        form.category_id.data = str(category_id)

    return form


def assert_party_has_categories_or_redirect(party: Party):
    categories = get_tournament_categories_for_party(party.id)
    if categories:
        return None

    flash_error(
        gettext(
            'Es existieren noch keine Kategorien. Bitte zuerst eine Kategorie anlegen.'
        )
    )
    return redirect_to('.category_index', party_id=party.id)


def get_create_wizard_state(party_id: str) -> dict:
    all_states = session.get(CREATE_WIZARD_SESSION_KEY, {})
    state = all_states.get(str(party_id), {})
    return dict(state)


def set_create_wizard_state(party_id: str, state: dict) -> None:
    all_states = dict(session.get(CREATE_WIZARD_SESSION_KEY, {}))
    all_states[str(party_id)] = state
    session[CREATE_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def clear_create_wizard_state(party_id: str) -> None:
    all_states = dict(session.get(CREATE_WIZARD_SESSION_KEY, {}))
    all_states.pop(str(party_id), None)
    session[CREATE_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def get_stage_builder_wizard_state(party_id: str, tournament_id: str) -> dict:
    all_states = dict(session.get(STAGE_BUILDER_WIZARD_SESSION_KEY, {}))
    party_states = all_states.get(str(party_id), {})
    if not isinstance(party_states, dict):
        return {}

    state = party_states.get(str(tournament_id), {})
    return dict(state) if isinstance(state, dict) else {}


def set_stage_builder_wizard_state(
    party_id: str, tournament_id: str, state: dict
) -> None:
    all_states = dict(session.get(STAGE_BUILDER_WIZARD_SESSION_KEY, {}))
    party_states = dict(all_states.get(str(party_id), {}))
    party_states[str(tournament_id)] = state
    all_states[str(party_id)] = party_states
    session[STAGE_BUILDER_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def clear_stage_builder_wizard_state(party_id: str, tournament_id: str) -> None:
    all_states = dict(session.get(STAGE_BUILDER_WIZARD_SESSION_KEY, {}))
    party_states = dict(all_states.get(str(party_id), {}))
    party_states.pop(str(tournament_id), None)
    if party_states:
        all_states[str(party_id)] = party_states
    else:
        all_states.pop(str(party_id), None)
    session[STAGE_BUILDER_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def slugify_tournament_title(value: str) -> str:
    normalized = (
        unicodedata.normalize('NFKD', value)
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug[:60]


def serialize_datetime_local(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime('%Y-%m-%dT%H:%M')


def deserialize_datetime_local(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None


def is_wizard_format_complete(state: dict) -> bool:
    return all(
        (
            state.get('category_id'),
            state.get('mode'),
            state.get('registration_mode'),
            state.get('team_size') is not None,
            state.get('substitute_count') is not None,
            state.get('coin_cost') is not None,
            state.get('coin_refund_policy'),
            state.get('coin_charge_mode'),
        )
    )


def is_wizard_details_complete(state: dict) -> bool:
    return bool(state.get('slug') and state.get('title'))


def is_wizard_schedule_complete(state: dict) -> bool:
    return 'registration_open' in state


def get_available_tournament_admin_users():
    role_ids_by_permission = authz_service.get_assigned_roles_for_permissions()
    role_ids = role_ids_by_permission.get('netsession_tourney.admin', set())

    user_ids: set[UserID] = set()
    for role_id in role_ids:
        user_ids.update(authz_service.find_user_ids_for_role(role_id))

    users = user_service.get_users(user_ids, include_avatars=True)
    return sorted(users, key=lambda user: user.screen_name.lower())


def parse_admin_user_ids(
    raw_user_ids: list[str] | None, available_user_ids: set[str]
) -> set[UserID]:
    if not raw_user_ids:
        return set()

    selected_user_ids: set[UserID] = set()
    for raw_user_id in raw_user_ids:
        if raw_user_id not in available_user_ids:
            continue

        try:
            selected_user_ids.add(UserID(UUID(raw_user_id)))
        except ValueError:
            continue

    return selected_user_ids
