"""
byceps.services.netsession_tourney.blueprints.site.match_state_labels
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

German labels for match states, shown to players.
"""

from flask_babel import gettext

from byceps.services.netsession_tourney.enum_labels import enum_label
from byceps.services.netsession_tourney.models import MatchState


_BRACKET_LABEL_FACTORIES = {
    MatchState.pending: lambda: gettext('Offen'),
    MatchState.ready: lambda: gettext('Bereit'),
    MatchState.in_progress: lambda: gettext('Live'),
    MatchState.pending_confirmation: lambda: gettext('Bestätigung'),
    MatchState.needs_admin_review: lambda: gettext('Prüfung'),
    MatchState.completed: lambda: gettext('Fertig'),
    MatchState.disputed: lambda: gettext('Strittig'),
}


def bracket_label(state: MatchState) -> str | None:
    """Return a short label that fits on a bracket card."""
    label_factory = _BRACKET_LABEL_FACTORIES.get(state)
    if label_factory is None:
        return None
    return label_factory()


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
