"""
byceps.services.netsession_tourney.browser_push_outbox_message
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Browser push message payloads: title, body, link, tag and match label.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .browser_push_outbox_match_label import (
    build_browser_push_match_label,
)
from .dbmodels import (
    DbNetsessionTourneyNotification,
    DbNetsessionTourneyTournament,
)
from .flatout2_races import (
    build_flatout2_first_race_summary,
)
from .notification_urls import (
    build_browser_push_badge_url,
    build_browser_push_logo_urls,
)


_FIXED_BODIES_BY_KIND: dict[str, str] = {
    'tournament_live': 'Turnier ist jetzt live.',
    'tournament_closed': 'Turnier wurde beendet.',
    'tournament_canceled': 'Turnier wurde abgesagt.',
    'checkin_open': (
        'Der Check-in ist offen – jetzt einchecken (bei Teams der Captain).'
    ),
}

# kind -> (body with `{match_label}`, body without a match label)
_MATCH_LABEL_BODIES_BY_KIND: dict[str, tuple[str, str]] = {
    'match_ready': (
        '{match_label} ist spielbereit.',
        'Dein Match ist spielbereit.',
    ),
    'result_submitted': (
        '{match_label}: Ergebnis wurde übermittelt.',
        'Für dein Match wurde ein Ergebnis übermittelt.',
    ),
    'schedule_changed': (
        '{match_label}: Matchzeit wurde geändert.',
        'Die Matchzeit wurde geändert.',
    ),
    'dispute_opened': (
        '{match_label}: Streitfall wurde geöffnet.',
        'Für dein Match wurde ein Streitfall geöffnet.',
    ),
}

_DEFAULT_BODY = 'Es gibt ein neues Update.'


def build_browser_push_message_payload(
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
) -> dict[str, Any]:
    payload = dict(db_notification.payload_json or {})
    kind = db_notification.kind
    match_label = build_browser_push_match_label(payload)
    title = str(payload.get('title') or '').strip() or db_tournament.title

    body = _build_browser_push_body(kind, payload, match_label)

    url = _get_browser_push_url(payload, db_tournament)

    tag_suffix, renotify = _get_browser_push_tag_suffix_and_renotify(
        kind, payload, db_tournament, db_notification
    )

    icon_url, image_url = build_browser_push_logo_urls(db_tournament)
    return {
        'title': title,
        'body': body[:180],
        'url': url,
        'tag': f'netsession-tourney-{kind}-{tag_suffix}',
        'renotify': renotify,
        'icon': icon_url,
        'badge': build_browser_push_badge_url(),
        'image': image_url,
    }


def _get_browser_push_url(
    payload: dict[str, Any], db_tournament: DbNetsessionTourneyTournament
) -> str:
    url = payload.get('url')
    if not isinstance(url, str) or not url:
        url = f'/ns-tourneys/{db_tournament.slug}'
    return url


def _get_browser_push_tag_suffix_and_renotify(
    kind: str,
    payload: dict[str, Any],
    db_tournament: DbNetsessionTourneyTournament,
    db_notification: DbNetsessionTourneyNotification,
) -> tuple[Any, bool]:
    if kind == 'manual_announcement':
        return db_notification.id, True

    tag_suffix = (
        payload.get('match_id') or payload.get('slug') or db_tournament.id
    )
    return tag_suffix, False


def _build_browser_push_body(
    kind: str, payload: dict[str, Any], match_label: str | None
) -> str:
    fixed_body = _FIXED_BODIES_BY_KIND.get(kind)
    if fixed_body is not None:
        return fixed_body

    match_label_bodies = _MATCH_LABEL_BODIES_BY_KIND.get(kind)
    if match_label_bodies is not None:
        with_label, without_label = match_label_bodies
        return (
            with_label.format(match_label=match_label)
            if match_label
            else without_label
        )

    build_body = _PAYLOAD_BODY_BUILDERS_BY_KIND.get(kind)
    if build_body is None:
        return _DEFAULT_BODY

    return build_body(payload, match_label)


def _build_browser_push_manual_announcement_body(
    payload: dict[str, Any], match_label: str | None
) -> str:
    return (
        str(payload.get('body') or '').strip()
        or 'Es gibt ein neues Turnier-Update.'
    )


def _build_browser_push_flatout2_host_body(
    payload: dict[str, Any], match_label: str | None
) -> str:
    first_race_summary = build_flatout2_first_race_summary(payload)
    base_body = (
        f'Du wurdest als Host für {match_label} ausgewählt.'
        if match_label
        else 'Du wurdest als Host für ein Match ausgewählt.'
    )
    return (
        f'{base_body} {first_race_summary}' if first_race_summary else base_body
    )


def _build_browser_push_chat_body(
    payload: dict[str, Any], match_label: str | None
) -> str:
    body_preview = str(payload.get('body_preview') or '').strip()
    return (
        (
            f'{match_label}: Neue Nachricht - {body_preview}'
            if match_label
            else f'Neue Match-Nachricht: {body_preview}'
        )
        if body_preview
        else (
            f'{match_label}: Neue Match-Nachricht.'
            if match_label
            else 'Neue Match-Nachricht.'
        )
    )


_PAYLOAD_BODY_BUILDERS_BY_KIND: dict[
    str, Callable[[dict[str, Any], str | None], str]
] = {
    'manual_announcement': _build_browser_push_manual_announcement_body,
    'flatout2_host_assigned': _build_browser_push_flatout2_host_body,
    'chat_message_posted': _build_browser_push_chat_body,
}
