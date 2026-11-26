"""
byceps.services.netsession_tourney.blueprints.api.serializer_match_parts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Parts of the match serialization for the tournament API: slots and results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from byceps.services.netsession_tourney.models import (
    Match,
    MatchResult,
    MatchSlot,
    MatchState,
    Participant,
    ParticipantStatus,
)
from byceps.services.netsession_tourney.score_parsing import (
    is_walkover_score_json,
    parse_match_result_slot_scores,
)

from .match_extras import (
    MatchExtras,
)


@dataclass(frozen=True, kw_only=True)
class MatchContext:
    participants_by_id: dict
    extras: MatchExtras
    # FFA matches only: participants that play on after this match.
    advancing_ids_by_match_id: dict


def _serialize_slot(
    slot: MatchSlot,
    result: MatchResult | None,
    context: MatchContext,
    is_bye: bool,
    advancing_ids: set | None,
) -> dict[str, Any]:
    participant = context.participants_by_id.get(slot.participant_id)
    source_match_id = context.extras.source_match_id_by_slot_id.get(slot.id)
    ranking = _get_result_ranking(result)
    key = str(slot.slot_no)
    return {
        'slot_no': slot.slot_no,
        **_serialize_slot_participant(slot, participant),
        'bye': is_bye,
        'withdrawn': _is_withdrawn(participant),
        'source': _serialize_slot_source(slot, source_match_id),
        'placement': (ranking.get('placements') or {}).get(key),
        'points': (ranking.get('points') or {}).get(key),
        'advances': _get_slot_advances(slot, advancing_ids),
    }


def _get_result_ranking(result: MatchResult | None) -> dict:
    return result.ranking if result and isinstance(result.ranking, dict) else {}


def _serialize_slot_participant(
    slot: MatchSlot, participant: Participant | None
) -> dict[str, Any]:
    return {
        'participant_id': str(slot.participant_id)
        if slot.participant_id
        else None,
        'name': participant.name if participant else None,
        'logo_url': participant.logo_url if participant else None,
    }


def _is_withdrawn(participant: Participant | None) -> bool:
    return (
        participant.status == ParticipantStatus.dropped
        if participant
        else False
    )


def _serialize_slot_source(
    slot: MatchSlot, source_match_id
) -> dict[str, Any] | None:
    return (
        {
            'match_id': str(source_match_id),
            'outcome': slot.source_outcome.value,
        }
        if source_match_id is not None
        else None
    )


def _get_slot_advances(
    slot: MatchSlot, advancing_ids: set | None
) -> bool | None:
    return (
        slot.participant_id in advancing_ids
        if advancing_ids is not None and slot.participant_id is not None
        else None
    )


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
    score_display = _get_score_display(score, scores, walkover)
    placements = ranking.get('placements')
    return {
        'winner_slot': result.winner_slot,
        'confirmed': match.state == MatchState.completed,
        'walkover': walkover,
        'score_display': score_display,
        'scores': scores,
        'placements': _serialize_placements(placements),
        'score': score,
        'ranking': ranking,
    }


def _get_score_display(score: dict, scores: dict, walkover: bool) -> str | None:
    display = score.get('display')
    if walkover:
        return 'kampflos'
    if isinstance(display, str) and display.strip():
        return display.strip()
    return ':'.join(str(scores[key]) for key in sorted(scores, key=int)) or None


def _serialize_placements(placements) -> dict:
    return (
        {str(key): value for key, value in placements.items()}
        if isinstance(placements, dict)
        else {}
    )


def _number(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value
