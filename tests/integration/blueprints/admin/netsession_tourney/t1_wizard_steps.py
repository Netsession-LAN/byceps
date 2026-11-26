"""Steps of the tournament creation wizard for the `test_t1_create_*`
tests.
"""

from dataclasses import dataclass
from io import BytesIO
import re

from PIL import Image

from byceps.services.netsession_tourney import (
    tournament_category_service,
    tournament_service,
)
from byceps.services.netsession_tourney.models import (
    Tournament,
    TournamentCategory,
)
from byceps.services.party.models import Party


ADMIN_BASE_URL = 'http://admin.acmecon.test/ns-tourneys'


@dataclass(frozen=True)
class WizardParty:
    party: Party
    category: TournamentCategory

    @property
    def url(self) -> str:
        return f'{ADMIN_BASE_URL}/for_party/{self.party.id}'

    def step_url(self, step: str) -> str:
        return f'{self.url}/create/{step}'


def create_wizard_party(make_party, brand) -> WizardParty:
    party = make_party(brand)
    category = tournament_category_service.create_tournament_category(
        party.id, 'T1 Main'
    ).unwrap()
    return WizardParty(party, category)


def post_format(client, wizard_party: WizardParty, **overrides):
    data = {
        'category_id': str(wizard_party.category.id),
        'mode': 'duel',
        'registration_mode': 'solo',
        'team_size': '1',
        'substitute_count': '0',
        'participant_limit': '',
        'coin_cost': '0',
        'coin_refund_policy': 'until_tournament_end',
        'coin_charge_mode': 'all_members',
    }
    data.update(overrides)
    return client.post(wizard_party.step_url('format'), data=data)


def post_details(client, wizard_party: WizardParty, **overrides):
    data = {'slug': 't1-wizard-cup', 'title': 'T1 Wizard Cup'}
    data.update(overrides)
    return client.post(wizard_party.step_url('details'), data=data)


def post_schedule(client, wizard_party: WizardParty, **overrides):
    data = {
        'starts_at': '2026-12-01T18:00',
        'visible_on_site': 'y',
        'registration_open': 'y',
    }
    data.update(overrides)
    return client.post(wizard_party.step_url('schedule'), data=data)


def find_tournament(party_id, slug: str) -> Tournament | None:
    return tournament_service.find_tournament_by_slug_for_party(party_id, slug)


def png() -> BytesIO:
    buffer = BytesIO()
    Image.new('RGB', (8, 8)).save(buffer, 'PNG')
    buffer.seek(0)
    return buffer


def is_selected(body: str, value: str) -> bool:
    """Tell if the option with the value is selected in the HTML."""
    value = re.escape(value)
    return bool(
        re.search(rf'<option selected value="{value}"', body)
        or re.search(rf'<option value="{value}" selected', body)
    )
