"""
byceps.services.netsession_tourney.blueprints.site.match_state_labels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

German labels for match states, shown to players.
"""

from flask_babel import gettext

from byceps.services.netsession_tourney.enum_labels import enum_label
from byceps.services.netsession_tourney.models import MatchState


def bracket_label(state: MatchState) -> str:
    """Return a short label that fits on a bracket card."""
    match state:
        case MatchState.pending:
            return gettext('Offen')
        case MatchState.ready:
            return gettext('Bereit')
        case MatchState.in_progress:
            return gettext('Live')
        case MatchState.pending_confirmation:
            return gettext('Bestätigung')
        case MatchState.needs_admin_review:
            return gettext('Prüfung')
        case MatchState.completed:
            return gettext('Fertig')
        case MatchState.disputed:
            return gettext('Strittig')


def open_label(state: MatchState) -> str:
    """Return the label for the list of open matches."""
    match state:
        case MatchState.ready:
            return gettext('Spielbereit')
        case MatchState.pending_confirmation:
            return gettext('Wartet auf Bestätigung')
        case MatchState.needs_admin_review:
            return gettext('Admin-Prüfung')
        case _:
            return bracket_label(state)


def open_class_name(state: MatchState) -> str:
    return {
        MatchState.ready: 'is-ready',
        MatchState.in_progress: 'is-live',
        MatchState.pending_confirmation: 'is-pending-confirmation',
        MatchState.needs_admin_review: 'is-needs-review',
    }.get(state, '')


def register_filters(blueprint) -> None:
    blueprint.add_app_template_filter(bracket_label, 'ns_match_state')
    blueprint.add_app_template_filter(open_label, 'ns_match_state_long')
    blueprint.add_app_template_filter(open_class_name, 'ns_match_state_class')
    blueprint.add_app_template_filter(enum_label, 'ns_label')
