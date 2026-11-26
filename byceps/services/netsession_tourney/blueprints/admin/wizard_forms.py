"""
byceps.services.netsession_tourney.blueprints.admin.wizard_forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Forms of the tournament creation wizard (see `wizard_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from byceps.services.netsession_tourney.blueprints.admin.wizard_form_data import (
    build_wizard_format_form_data,
)
from byceps.services.netsession_tourney.blueprints.admin.wizard_helpers import (
    deserialize_datetime_local,
    get_available_tournament_admin_users,
    set_category_choices_for_form,
    slugify_tournament_title,
)
from byceps.services.netsession_tourney.forms import (
    TournamentForm,
    TournamentWizardDetailsForm,
    TournamentWizardFormatForm,
    TournamentWizardScheduleForm,
)
from byceps.services.netsession_tourney.logo_service import (
    get_discord_forum_image_choices,
    get_sponsor_logo_choices,
    get_tournament_logo_choices,
)
from byceps.services.netsession_tourney.tournament_category_service import (
    get_tournament_categories_for_party,
)
from byceps.services.netsession_tourney.tournament_rule_template_service import (
    get_tournament_rule_templates_for_party,
)
from byceps.services.party.models import Party

from .route_config import (
    DISCORD_FORUM_EVENT_CHOICES,
)


def set_rules_template_choices_for_form(
    form: TournamentForm | TournamentWizardDetailsForm,
    party_id: str,
    *,
    selected_slug: str | None = None,
) -> None:
    rule_templates = get_tournament_rule_templates_for_party(party_id)
    choices = [(template.slug, template.title) for template in rule_templates]

    if selected_slug and selected_slug not in {slug for slug, _ in choices}:
        choices.insert(0, (selected_slug, f'{selected_slug} (nicht gefunden)'))

    form.set_rules_template_choices(choices)


def set_logo_choices_for_form(
    form: TournamentForm | TournamentWizardDetailsForm,
    party_id: str,
    *,
    selected_tournament_logo_url: str | None = None,
    selected_sponsor_logo_url: str | None = None,
) -> None:
    tournament_logo_choices = get_tournament_logo_choices(party_id)
    if selected_tournament_logo_url and selected_tournament_logo_url not in {
        url for url, _ in tournament_logo_choices
    }:
        tournament_logo_choices.insert(
            0,
            (
                selected_tournament_logo_url,
                f'{selected_tournament_logo_url} (nicht gefunden)',
            ),
        )
    form.set_tournament_logo_choices(tournament_logo_choices)

    sponsor_logo_choices = get_sponsor_logo_choices(party_id)
    if selected_sponsor_logo_url and selected_sponsor_logo_url not in {
        url for url, _ in sponsor_logo_choices
    }:
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


def build_wizard_format_form(
    party_id: str,
    *,
    state: dict,
    erroneous_form: TournamentWizardFormatForm | None = None,
) -> tuple[TournamentWizardFormatForm, set[str]]:
    form = (
        erroneous_form
        if erroneous_form is not None
        else TournamentWizardFormatForm(
            data=build_wizard_format_form_data(state)
        )
    )

    set_category_choices_for_form(form, party_id)

    if erroneous_form is None and not form.category_id.data:
        _set_default_category_id(form, party_id)

    available_admin_users = get_available_tournament_admin_users()
    available_admin_user_ids = {str(user.id) for user in available_admin_users}
    form.set_admin_user_choices(
        [(str(user.id), user.screen_name) for user in available_admin_users]
    )

    return form, available_admin_user_ids


def _set_default_category_id(
    form: TournamentWizardFormatForm, party_id: str
) -> None:
    default_category_id = _get_default_category_id_for_party(party_id)
    if default_category_id is not None:
        form.category_id.data = default_category_id


def build_wizard_details_form(
    party_id: str,
    *,
    state: dict,
    erroneous_form: TournamentWizardDetailsForm | None = None,
) -> TournamentWizardDetailsForm:
    if erroneous_form is not None:
        form = erroneous_form
    else:
        form = TournamentWizardDetailsForm(
            data=_build_wizard_details_form_data(state)
        )

    set_logo_choices_for_form(
        form,
        party_id,
        selected_tournament_logo_url=state.get('logo_url'),
        selected_sponsor_logo_url=state.get('sponsor_logo_url'),
    )
    set_rules_template_choices_for_form(
        form,
        party_id,
        selected_slug=state.get('rules_page_slug'),
    )
    form.set_discord_forum_image_choices(
        get_discord_forum_image_choices(party_id)
    )
    form.event_mask.choices = DISCORD_FORUM_EVENT_CHOICES
    return form


def _build_wizard_details_form_data(state: dict) -> dict:
    title = state.get('title') or ''
    slug = state.get('slug') or ''
    if not slug and title:
        slug = slugify_tournament_title(title)

    return {
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
        'discord_forum_image_url': state.get('discord_forum_image_url'),
        'applied_tag_ids': ', '.join(
            state.get('discord_applied_tag_ids') or []
        ),
        'event_mask': state.get('discord_event_mask') or [],
    }


def build_wizard_schedule_form(
    *,
    party: Party,
    state: dict,
    erroneous_form: TournamentWizardScheduleForm | None = None,
) -> TournamentWizardScheduleForm:
    if erroneous_form is not None:
        return erroneous_form

    starts_at = deserialize_datetime_local(state.get('starts_at'))
    if starts_at is None:
        starts_at = party.starts_at

    return TournamentWizardScheduleForm(
        data={
            'starts_at': starts_at,
            'visible_on_site': state.get('visible_on_site', True),
            'registration_open': state.get('registration_open', True),
            'registration_deadline': deserialize_datetime_local(
                state.get('registration_deadline')
            ),
            'roster_lock_at': deserialize_datetime_local(
                state.get('roster_lock_at')
            ),
            'checkin_open_at': deserialize_datetime_local(
                state.get('checkin_open_at')
            ),
            'checkin_close_at': deserialize_datetime_local(
                state.get('checkin_close_at')
            ),
        }
    )
