"""
byceps.services.netsession_tourney.blueprints.site.match_state_labels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

German labels for match states, shown to players.
"""

from flask_babel import gettext

from ...models import MatchState


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
            return gettext('Admin-Review')
        case _:
            return bracket_label(state)


def open_class_name(state: MatchState) -> str:
    return {
        MatchState.ready: 'is-ready',
        MatchState.in_progress: 'is-live',
        MatchState.pending_confirmation: 'is-pending-confirmation',
        MatchState.needs_admin_review: 'is-needs-review',
    }.get(state, '')
