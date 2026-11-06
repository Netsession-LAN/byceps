"""
byceps.services.netsession_tourney.blueprints.admin.wizard_helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from uuid import UUID

from flask import abort, session
from flask_babel import gettext

from byceps.services.authz import authz_service
from byceps.services.party.models import Party
from byceps.services.user import user_service
from byceps.services.user.models import UserID
from byceps.util.framework.flash import flash_error
from byceps.util.views import redirect_to

from ...forms import (
    TournamentForm,
    TournamentWizardDetailsForm,
    TournamentWizardFormatForm,
    TournamentWizardScheduleForm,
)
from ...logo_service import (
    find_discord_forum_image_asset,
    find_sponsor_logo_asset,
    find_tournament_logo_asset,
    get_discord_forum_image_choices,
    get_sponsor_logo_choices,
    get_tournament_logo_choices,
)
from ...models import (
    CoinChargeMode,
    CoinRefundPolicy,
    DiscordForumImageAssetID,
    RegistrationMode,
    SponsorLogoAssetID,
    TournamentCategoryID,
    TournamentLogoAssetID,
    TournamentPrizeID,
    TournamentMode,
    TournamentRuleTemplateID,
)
from ...tournament_category_service import (
    find_tournament_category,
    get_tournament_categories_for_party,
)
from ...tournament_prize_service import find_tournament_prize
from ...tournament_rule_template_service import (
    find_tournament_rule_template,
    get_tournament_rule_templates_for_party,
)
from .route_config import (
    CREATE_WIZARD_SESSION_KEY,
    DISCORD_FORUM_EVENT_CHOICES,
    STAGE_BUILDER_WIZARD_SESSION_KEY,
)


def _set_category_choices_for_form(
    form: TournamentForm | TournamentWizardFormatForm, party_id: str
) -> None:
    categories = get_tournament_categories_for_party(party_id)
    form.set_category_choices(
        [(str(category.id), category.title) for category in categories]
    )


def _set_rules_template_choices_for_form(
    form: TournamentForm | TournamentWizardDetailsForm,
    party_id: str,
    *,
    selected_slug: str | None = None,
) -> None:
    rule_templates = get_tournament_rule_templates_for_party(party_id)
    choices = [(template.slug, template.title) for template in rule_templates]

    if (
        selected_slug
        and selected_slug not in {slug for slug, _ in choices}
    ):
        choices.insert(0, (selected_slug, f'{selected_slug} (nicht gefunden)'))

    form.set_rules_template_choices(choices)


def _set_logo_choices_for_form(
    form: TournamentForm | TournamentWizardDetailsForm,
    party_id: str,
    *,
    selected_tournament_logo_url: str | None = None,
    selected_sponsor_logo_url: str | None = None,
) -> None:
    tournament_logo_choices = get_tournament_logo_choices(party_id)
    if (
        selected_tournament_logo_url
        and selected_tournament_logo_url
        not in {url for url, _ in tournament_logo_choices}
    ):
        tournament_logo_choices.insert(
            0,
            (
                selected_tournament_logo_url,
                f'{selected_tournament_logo_url} (nicht gefunden)',
            ),
        )
    form.set_tournament_logo_choices(tournament_logo_choices)

    sponsor_logo_choices = get_sponsor_logo_choices(party_id)
    if (
        selected_sponsor_logo_url
        and selected_sponsor_logo_url not in {url for url, _ in sponsor_logo_choices}
    ):
        sponsor_logo_choices.insert(
            0,
            (
                selected_sponsor_logo_url,
                f'{selected_sponsor_logo_url} (nicht gefunden)',
            ),
        )
    form.set_sponsor_logo_choices(sponsor_logo_choices)


def _get_default_category_id_for_party(party_id: str) -> str | None:
    categories = get_tournament_categories_for_party(party_id)
    if not categories:
        return None

    return str(categories[0].id)


def _parse_category_id(raw_category_id: str | None) -> TournamentCategoryID | None:
    if not raw_category_id:
        return None

    try:
        return TournamentCategoryID(UUID(raw_category_id))
    except ValueError:
        return None


def _get_tournament_category_or_404(category_id):
    category = find_tournament_category(TournamentCategoryID(category_id))
    if category is None:
        abort(404)

    return category


def _get_tournament_rule_template_or_404(rule_template_id):
    rule_template = find_tournament_rule_template(
        TournamentRuleTemplateID(rule_template_id)
    )
    if rule_template is None:
        abort(404)

    return rule_template


def _get_tournament_prize_or_404(prize_id):
    prize = find_tournament_prize(TournamentPrizeID(prize_id))
    if prize is None:
        abort(404)

    return prize


def _get_tournament_logo_asset_or_404(logo_asset_id):
    logo_asset = find_tournament_logo_asset(TournamentLogoAssetID(logo_asset_id))
    if logo_asset is None:
        abort(404)

    return logo_asset


def _get_sponsor_logo_asset_or_404(logo_asset_id):
    logo_asset = find_sponsor_logo_asset(SponsorLogoAssetID(logo_asset_id))
    if logo_asset is None:
        abort(404)

    return logo_asset


def _get_discord_forum_image_asset_or_404(image_asset_id):
    image_asset = find_discord_forum_image_asset(
        DiscordForumImageAssetID(image_asset_id)
    )
    if image_asset is None:
        abort(404)

    return image_asset


def _update_form_with_categories(
    party_id: str,
    *,
    category_id: TournamentCategoryID,
    erroneous_form=None,
):
    form = erroneous_form if erroneous_form else TournamentForm()
    _set_category_choices_for_form(form, party_id)
    if erroneous_form is None:
        form.category_id.data = str(category_id)

    return form


def _assert_party_has_categories_or_redirect(party: Party):
    categories = get_tournament_categories_for_party(party.id)
    if categories:
        return None

    flash_error(
        gettext(
            'Es existieren noch keine Kategorien. Bitte zuerst eine Kategorie anlegen.'
        )
    )
    return redirect_to('.category_index', party_id=party.id)


def _get_create_wizard_state(party_id: str) -> dict:
    all_states = session.get(CREATE_WIZARD_SESSION_KEY, {})
    state = all_states.get(str(party_id), {})
    return dict(state)


def _set_create_wizard_state(party_id: str, state: dict) -> None:
    all_states = dict(session.get(CREATE_WIZARD_SESSION_KEY, {}))
    all_states[str(party_id)] = state
    session[CREATE_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def _clear_create_wizard_state(party_id: str) -> None:
    all_states = dict(session.get(CREATE_WIZARD_SESSION_KEY, {}))
    all_states.pop(str(party_id), None)
    session[CREATE_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def _get_stage_builder_wizard_state(party_id: str, tournament_id: str) -> dict:
    all_states = dict(session.get(STAGE_BUILDER_WIZARD_SESSION_KEY, {}))
    party_states = all_states.get(str(party_id), {})
    if not isinstance(party_states, dict):
        return {}

    state = party_states.get(str(tournament_id), {})
    return dict(state) if isinstance(state, dict) else {}


def _set_stage_builder_wizard_state(
    party_id: str, tournament_id: str, state: dict
) -> None:
    all_states = dict(session.get(STAGE_BUILDER_WIZARD_SESSION_KEY, {}))
    party_states = dict(all_states.get(str(party_id), {}))
    party_states[str(tournament_id)] = state
    all_states[str(party_id)] = party_states
    session[STAGE_BUILDER_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def _clear_stage_builder_wizard_state(party_id: str, tournament_id: str) -> None:
    all_states = dict(session.get(STAGE_BUILDER_WIZARD_SESSION_KEY, {}))
    party_states = dict(all_states.get(str(party_id), {}))
    party_states.pop(str(tournament_id), None)
    if party_states:
        all_states[str(party_id)] = party_states
    else:
        all_states.pop(str(party_id), None)
    session[STAGE_BUILDER_WIZARD_SESSION_KEY] = all_states
    session.modified = True


def _slugify_tournament_title(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value).encode(
        'ascii', 'ignore'
    ).decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug[:60]


def _serialize_datetime_local(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime('%Y-%m-%dT%H:%M')


def _deserialize_datetime_local(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None


def _is_wizard_format_complete(state: dict) -> bool:
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


def _is_wizard_details_complete(state: dict) -> bool:
    return bool(state.get('slug') and state.get('title'))


def _is_wizard_schedule_complete(state: dict) -> bool:
    return 'registration_open' in state


def _build_wizard_format_form(
    party_id: str,
    *,
    state: dict,
    erroneous_form: TournamentWizardFormatForm | None = None,
) -> tuple[TournamentWizardFormatForm, set[str]]:
    form = (
        erroneous_form
        if erroneous_form is not None
        else TournamentWizardFormatForm(
            data={
                'category_id': state.get('category_id'),
                'mode': state.get('mode') or TournamentMode.duel.value,
                'registration_mode': state.get('registration_mode')
                or RegistrationMode.solo.value,
                'team_size': state.get('team_size') or 1,
                'substitute_count': state.get('substitute_count') or 0,
                'participant_limit': state.get('participant_limit'),
                'coin_cost': state.get('coin_cost', 0),
                'coin_refund_policy': state.get('coin_refund_policy')
                or CoinRefundPolicy.until_tournament_end.value,
                'coin_charge_mode': state.get('coin_charge_mode')
                or CoinChargeMode.all_members.value,
                'admin_user_ids': state.get('admin_user_ids') or [],
            }
        )
    )

    _set_category_choices_for_form(form, party_id)

    if erroneous_form is None and not form.category_id.data:
        default_category_id = _get_default_category_id_for_party(party_id)
        if default_category_id is not None:
            form.category_id.data = default_category_id

    available_admin_users = _get_available_tournament_admin_users()
    available_admin_user_ids = {str(user.id) for user in available_admin_users}
    form.set_admin_user_choices(
        [(str(user.id), user.screen_name) for user in available_admin_users]
    )

    return form, available_admin_user_ids


def _build_wizard_details_form(
    party_id: str,
    *,
    state: dict,
    erroneous_form: TournamentWizardDetailsForm | None = None,
) -> TournamentWizardDetailsForm:
    if erroneous_form is not None:
        form = erroneous_form
    else:
        title = state.get('title') or ''
        slug = state.get('slug') or ''
        if not slug and title:
            slug = _slugify_tournament_title(title)

        form = TournamentWizardDetailsForm(
            data={
                'slug': slug,
                'title': title,
                'subtitle': state.get('subtitle'),
                'tournament_logo_url': state.get('logo_url'),
                'is_sponsored': state.get('is_sponsored', False),
                'sponsor_logo_url': state.get('sponsor_logo_url'),
                'game': state.get('game'),
                'rules_template_slug': state.get('rules_page_slug'),
                'discord_enabled': state.get('discord_enabled', False),
                'forum_channel_id': state.get('discord_forum_channel_id'),
                'discord_forum_image_url': state.get(
                    'discord_forum_image_url'
                ),
                'applied_tag_ids': ', '.join(
                    state.get('discord_applied_tag_ids') or []
                ),
                'event_mask': state.get('discord_event_mask') or [],
            }
        )

    _set_logo_choices_for_form(
        form,
        party_id,
        selected_tournament_logo_url=state.get('logo_url'),
        selected_sponsor_logo_url=state.get('sponsor_logo_url'),
    )
    _set_rules_template_choices_for_form(
        form,
        party_id,
        selected_slug=state.get('rules_page_slug'),
    )
    form.set_discord_forum_image_choices(
        get_discord_forum_image_choices(party_id)
    )
    form.event_mask.choices = DISCORD_FORUM_EVENT_CHOICES
    return form


def _build_wizard_schedule_form(
    *,
    party: Party,
    state: dict,
    erroneous_form: TournamentWizardScheduleForm | None = None,
) -> TournamentWizardScheduleForm:
    if erroneous_form is not None:
        return erroneous_form

    starts_at = _deserialize_datetime_local(state.get('starts_at'))
    if starts_at is None:
        starts_at = party.starts_at

    return TournamentWizardScheduleForm(
        data={
            'starts_at': starts_at,
            'visible_on_site': state.get('visible_on_site', True),
            'registration_open': state.get('registration_open', True),
            'registration_deadline': _deserialize_datetime_local(
                state.get('registration_deadline')
            ),
            'roster_lock_at': _deserialize_datetime_local(
                state.get('roster_lock_at')
            ),
            'checkin_open_at': _deserialize_datetime_local(
                state.get('checkin_open_at')
            ),
            'checkin_close_at': _deserialize_datetime_local(
                state.get('checkin_close_at')
            ),
        }
    )


def _get_available_tournament_admin_users():
    role_ids_by_permission = authz_service.get_assigned_roles_for_permissions()
    role_ids = role_ids_by_permission.get('netsession_tourney.admin', set())

    user_ids: set[UserID] = set()
    for role_id in role_ids:
        user_ids.update(authz_service.find_user_ids_for_role(role_id))

    users = user_service.get_users(user_ids, include_avatars=True)
    return sorted(users, key=lambda user: user.screen_name.lower())


def _parse_admin_user_ids(
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


