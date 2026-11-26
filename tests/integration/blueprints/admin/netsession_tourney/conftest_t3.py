"""Fixtures of the t3 admin tests (tournament, participant and match
pages).

Loaded per test module via `pytest_plugins`; every fixture name starts
with `t3_` so it cannot clash with fixtures of other test areas.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from html.parser import HTMLParser
from typing import Any

import pytest

from byceps.application import create_admin_app
from byceps.config.models import AdminWebAppConfig
from byceps.database import db
from byceps.services.netsession_tourney import (
    match_generation,
    match_queries,
    registration_service,
    stage_service,
    tournament_lifecycle_service,
    tournament_queries,
    tournament_service,
)

# Import the admin blueprint while no app context is active: its
# `route_config` translates labels at import time, which needs a user
# inside an app context (`admin_app` keeps one pushed).
from byceps.services.netsession_tourney.blueprints.admin import (  # noqa: F401
    views as _admin_views,
)
from byceps.services.netsession_tourney.models import (
    RegistrationMode,
    StageType,
    TournamentMode,
)
from byceps.services.ticketing import (
    ticket_creation_service,
    ticket_user_management_service,
)

from tests.helpers import generate_token, log_in_user


ADMIN_BASE = 'http://admin.acmecon.test/ns-tourneys'

MANAGER_PERMISSIONS = {
    'admin.access',
    'netsession_tourney.view',
    'netsession_tourney.manage',
}


@pytest.fixture(scope='session')
def t3_app(admin_app, make_byceps_config):
    """Admin app with the tournament system switched on."""
    byceps_config = replace(
        make_byceps_config(), netsession_tourney_enabled=True
    )
    return create_admin_app(
        byceps_config, AdminWebAppConfig(server_name='admin.acmecon.test')
    )


@pytest.fixture(scope='session')
def t3_manager(make_admin):
    manager = make_admin(MANAGER_PERMISSIONS)
    log_in_user(manager.id)
    return manager


@pytest.fixture(scope='module')
def t3_client(make_client, t3_app, t3_manager):
    return make_client(t3_app, user_id=t3_manager.id)


@pytest.fixture(scope='module')
def t3_viewer_client(make_client, t3_app, make_admin):
    viewer = make_admin({'admin.access', 'netsession_tourney.view'})
    log_in_user(viewer.id)
    return make_client(t3_app, user_id=viewer.id)


@pytest.fixture(scope='module')
def t3_party(make_party, brand):
    return make_party(brand)


@dataclass
class Tourney:
    party: Any
    tournament: Any
    stage: Any
    players: list[Any]

    @property
    def url(self) -> str:
        return f'{ADMIN_BASE}/for_party/{self.party.id}/tournaments/{self.tournament.id}'

    def reload(self) -> Any:
        db.session.expire_all()
        return tournament_service.find_tournament_for_party(
            self.party.id, self.tournament.id
        )

    def participants(self, include_dropped: bool = False) -> list[Any]:
        db.session.expire_all()
        return tournament_queries.get_participants_for_tournament(
            self.party.id, self.tournament.id, include_dropped=include_dropped
        )

    def participant_of(self, user: Any) -> Any:
        return next(p for p in self.participants(True) if p.user_id == user.id)

    def matches(self) -> list[Any]:
        db.session.expire_all()
        return sorted(
            match_queries.get_matches_for_tournament(
                self.party.id, self.tournament.id
            ),
            key=lambda m: (m.round_no, m.match_no),
        )

    def slots(self, match: Any) -> list[Any]:
        db.session.expire_all()
        slots = match_queries.get_match_slots({match.id}).get(match.id, [])
        return sorted(slots, key=lambda s: s.slot_no)

    def match(self, match_id: Any) -> Any:
        return next(m for m in self.matches() if m.id == match_id)

    def open_matches(self) -> list[Any]:
        return [
            m
            for m in self.matches()
            if m.state.value in {'ready', 'in_progress'}
            and len([s for s in self.slots(m) if s.participant_id]) >= 2
        ]


@pytest.fixture(scope='module')
def t3_make_players(make_user, make_ticket_category):
    def _wrapper(party: Any, count: int) -> list[Any]:
        category = make_ticket_category(party.id, 'T3-' + generate_token())
        players = []
        for _ in range(count):
            player = make_user('T3_' + generate_token(6))
            ticket = ticket_creation_service.create_ticket(category, player)
            ticket_user_management_service.appoint_user(
                ticket.id, player, player
            ).unwrap()
            players.append(player)
        return players

    return _wrapper


@pytest.fixture(scope='module')
def t3_make_tourney(t3_party, t3_manager, t3_make_players):
    """Create a tournament with one stage and `count` registered players;
    optionally publish it and generate the stage's matches."""

    def _wrapper(
        stage_type: StageType = StageType.single_elimination,
        count: int = 4,
        *,
        mode: TournamentMode = TournamentMode.duel,
        registration_mode: RegistrationMode = RegistrationMode.solo,
        settings: dict | None = None,
        publish: bool = True,
        generate: bool = True,
        party: Any = None,
        **tournament_kwargs: Any,
    ) -> Tourney:
        party = party or t3_party
        tournament = tournament_service.create_tournament(
            party.id,
            't3-' + generate_token(6).lower(),
            'T3 Cup ' + generate_token(),
            mode,
            registration_mode,
            t3_manager,
            **tournament_kwargs,
        ).unwrap()
        stage = stage_service.create_stage(
            party.id,
            tournament.id,
            stage_type,
            'T3 Stage',
            settings or {},
            t3_manager,
        ).unwrap()
        players = t3_make_players(party, count)
        if registration_mode == RegistrationMode.solo:
            for player in players:
                registration_service.register_user(
                    party.id, tournament.id, player
                ).unwrap()
        if publish:
            tournament_lifecycle_service.publish_tournament(
                party.id, tournament.id, t3_manager
            ).unwrap()
        if generate:
            match_generation.generate_stage_matches(
                party.id, tournament.id, stage.id, t3_manager
            ).unwrap()
        return Tourney(party, tournament, stage, players)

    return _wrapper


def _pop_flashes(client) -> list[tuple[str, str]]:
    """Return (and remove) the flashed messages as (category, text)."""
    with client.session_transaction() as session:
        flashes = session.pop('_flashes', [])
    return [(message['category'], message['text']) for _, message in flashes]


@pytest.fixture(scope='session')
def t3_flashes():
    """Return the flashed messages of a client as (category, text)."""
    return _pop_flashes


@pytest.fixture(scope='session')
def t3_assert_flash():
    """Assert that the client got this flash message."""

    def _wrapper(client, category: str, text: str) -> None:
        flashes = _pop_flashes(client)
        assert (category, text) in flashes, flashes

    return _wrapper


class _FormExtractor(HTMLParser):
    """Collect POST forms with the values a browser would submit."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[dict[str, Any]] = []
        self._fields: list | None = None
        self._select: str | None = None
        self._select_values: list[str] = []
        self._textarea: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self._fields = []
            self.forms.append({'action': a.get('action') or '', 'fields': []})
            self.forms[-1]['fields'] = self._fields
        elif self._fields is not None:
            self._handle_field(tag, a)

    def _handle_field(self, tag, a):
        if tag == 'input' and a.get('name') and 'disabled' not in a:
            type_ = (a.get('type') or 'text').lower()
            if type_ in {'checkbox', 'radio'}:
                if 'checked' in a:
                    self._fields.append((a['name'], a.get('value', 'y')))
            elif type_ not in {'submit', 'button', 'file', 'reset'}:
                self._fields.append((a['name'], a.get('value', '')))
        elif tag == 'select':
            self._select = a.get('name')
            self._select_values = []
        elif tag == 'option' and self._select:
            if 'selected' in a:
                self._fields.append((self._select, a.get('value', '')))
        elif tag == 'textarea':
            self._textarea = a.get('name')
            self._fields.append((self._textarea, ''))

    def handle_endtag(self, tag):
        if tag == 'form':
            self._fields = None
        elif tag == 'select':
            self._select = None
        elif tag == 'textarea':
            self._textarea = None

    def handle_data(self, data):
        if self._textarea and self._fields:
            name, value = self._fields[-1]
            self._fields[-1] = (name, value + data)


def _extract_form(html: str, action_contains: str) -> list[tuple[str, str]]:
    parser = _FormExtractor()
    parser.feed(html)
    return next(
        form['fields']
        for form in parser.forms
        if action_contains in form['action']
    )


@pytest.fixture(scope='session')
def t3_form_fields():
    """Return the fields of the first form whose action matches."""
    return _extract_form
