"""
byceps.services.netsession_tourney.blueprints.api.serializers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

JSON shapes of the tournament API (see `docs/netsession/modules/
netsession_tourney.md`, section API). Scores are offered raw and
normalized, so clients need not parse the stored JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
import re
from typing import Any

from ...models import (
    Match,
    MatchResult,
    MatchSlot,
    MatchState,
    Participant,
    Stage,
    TournamentPrize,
)
from .match_extras import (
    MatchExtras,
    bye_slot_ids,
    describe_match,
)
from ...score_parsing import (
    is_walkover_score_json,
    parse_match_result_slot_scores,
)


DISPLAY_SETTING_KEYS = ('best_of', 'map_count')
STAGE_PHASES = {'draft': 'planned', 'live': 'running', 'closed': 'completed'}
TOURNAMENT_PHASES = {**STAGE_PHASES, 'canceled': 'canceled'}


@dataclass(frozen=True, kw_only=True)
class MatchContext:
    participants_by_id: dict
    extras: MatchExtras
    # FFA matches only: participants that play on after this match.
    advancing_ids_by_match_id: dict


def serialize_tournament(tournament) -> dict[str, Any]:
    return {
        'id': str(tournament.id),
        'party_id': tournament.party_id,
        'category_id': str(tournament.category_id),
        'slug': tournament.slug,
        'title': tournament.title,
        'subtitle': tournament.subtitle,
        'game': tournament.game,
        'mode': tournament.mode.value,
        'status': tournament.status.value,
        'phase': TOURNAMENT_PHASES.get(tournament.status.value),
        'starts_at': _iso(tournament.starts_at),
        'registration_open': tournament.registration_open,
    }


def serialize_stage(
    stage: Stage, *, tables: list | None, rounds_total: int | None
) -> dict[str, Any]:
    return {
        'id': str(stage.id),
        'order_no': stage.order_no,
        'type': stage.type.value,
        'name': stage.name,
        'status': stage.status.value,
        'phase': STAGE_PHASES.get(stage.status.value),
        'advance_count': _advance_count(stage),
        'rounds_total': rounds_total,
        'groups': tables,
        'settings': stage.settings,
    }


def _advance_count(stage: Stage) -> int | None:
    """Qualifier count of this stage as a target (`qualifier_top_n`), if
    set explicitly."""
    settings = stage.settings or {}
    if settings.get('builder_auto_qualifier_count'):
        return None
    value = settings.get('qualifier_top_n_per_match') or settings.get(
        'qualifier_top_n'
    )
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def serialize_participant(participant: Participant) -> dict[str, Any]:
    return {
        'id': str(participant.id),
        'name': participant.name,
        'type': participant.type.value,
        'logo_url': participant.logo_url,
        'seed': participant.seed,
        'status': participant.status.value,
        'checkin_state': participant.checkin_state.value,
    }


def serialize_match(
    match: Match,
    slots: list[MatchSlot],
    result: MatchResult | None,
    context: MatchContext,
) -> dict[str, Any]:
    bye_ids = bye_slot_ids(slots, context.extras)
    advancing_ids = context.advancing_ids_by_match_id.get(match.id)
    return {
        'id': str(match.id),
        'stage_id': str(match.stage_id),
        'round_no': match.round_no,
        'match_no': match.match_no,
        'state': match.state.value,
        'scheduled_at': _iso(match.scheduled_at),
        **describe_match(match, context.extras),
        'slots': [
            _serialize_slot(
                slot, result, context, slot.id in bye_ids, advancing_ids
            )
            for slot in sorted(slots, key=lambda slot: slot.slot_no)
        ],
        'result': _serialize_result(match, slots, result),
        'settings': {
            key: match.settings[key]
            for key in DISPLAY_SETTING_KEYS
            if isinstance(match.settings, dict) and key in match.settings
        },
    }


def _serialize_slot(
    slot: MatchSlot,
    result: MatchResult | None,
    context: MatchContext,
    is_bye: bool,
    advancing_ids: set | None,
) -> dict[str, Any]:
    participant = context.participants_by_id.get(slot.participant_id)
    source_match_id = context.extras.source_match_id_by_slot_id.get(slot.id)
    ranking = (
        result.ranking if result and isinstance(result.ranking, dict) else {}
    )
    key = str(slot.slot_no)
    return {
        'slot_no': slot.slot_no,
        'participant_id': str(slot.participant_id)
        if slot.participant_id
        else None,
        'name': participant.name if participant else None,
        'logo_url': participant.logo_url if participant else None,
        'bye': is_bye,
        'source': (
            {
                'match_id': str(source_match_id),
                'outcome': slot.source_outcome.value,
            }
            if source_match_id is not None
            else None
        ),
        'placement': (ranking.get('placements') or {}).get(key),
        'points': (ranking.get('points') or {}).get(key),
        'advances': (
            slot.participant_id in advancing_ids
            if advancing_ids is not None and slot.participant_id is not None
            else None
        ),
    }


def _serialize_result(
    match: Match, slots: list[MatchSlot], result: MatchResult | None
) -> dict[str, Any] | None:
    if result is None:
        return None
    score = result.score if isinstance(result.score, dict) else {}
    ranking = result.ranking if isinstance(result.ranking, dict) else {}
    walkover = is_walkover_score_json(score)
    scores = {
        str(slot_no): _number(value)
        for slot_no, value in parse_match_result_slot_scores(
            slots, score, winner_slot=result.winner_slot
        ).items()
    }
    display = score.get('display')
    if walkover:
        score_display = 'kampflos'
    elif isinstance(display, str) and display.strip():
        score_display = display.strip()
    else:
        score_display = (
            ':'.join(str(scores[key]) for key in sorted(scores, key=int))
            or None
        )
    placements = ranking.get('placements')
    return {
        'winner_slot': result.winner_slot,
        'confirmed': match.state == MatchState.completed,
        'walkover': walkover,
        'score_display': score_display,
        'scores': scores,
        'placements': (
            {str(key): value for key, value in placements.items()}
            if isinstance(placements, dict)
            else {}
        ),
        'score': score,
        'ranking': ranking,
    }


def serialize_standing(row: dict, prizes_by_position: dict) -> dict[str, Any]:
    participant = row['participant']
    prize = prizes_by_position.get(row.get('rank'))
    return {
        'rank': row.get('rank'),
        'participant_id': str(participant.id),
        'name': participant.name,
        'logo_url': participant.logo_url,
        'prize': _serialize_prize(prize) if prize else None,
    }


def _serialize_prize(prize: TournamentPrize) -> dict[str, Any]:
    return {
        'title': plain_prize_title(prize.body),
        'sponsor': None,
        'body': prize.body,
        'body_format': prize.body_format.value,
    }


def plain_prize_title(body: str) -> str:
    """First non-empty line of the prize text without HTML/Markdown marks."""
    text = re.sub(r'<[^>]+>', '\n', body or '')
    for line in text.splitlines():
        line = re.sub(r'[#*_`>]+', '', line).strip(' -\t')
        if line:
            return line
    return ''


def _number(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _iso(value: datetime | None) -> str | None:
    """Stored as naive UTC; output with offset."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
