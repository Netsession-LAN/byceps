"""
byceps.services.netsession_tourney.blueprints.admin.routes_participants_match_result
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Steps of the admin route that sets a match result (see
`routes_participants_matches`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from typing import Any

from flask import g, request
from flask_babel import gettext

from byceps.services.netsession_tourney.blueprints.admin.result_helpers import (
    build_score_payload,
    get_or_create_idempotency_key,
    parse_admin_ffa_result_form,
    parse_admin_flatout2_result_form,
)
from byceps.services.netsession_tourney.blueprints.admin.result_redirects import (
    redirect_to_match_or_tournament_view,
)
from byceps.services.netsession_tourney.blueprints.admin.routes_tournament_form_checks import (
    stripped_or_none,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_flatout2_generation import (
    is_flatout2_stage_type,
)
from byceps.services.netsession_tourney.blueprints.admin.stage_builder_stage_form_data import (
    is_ffa_result_stage_type,
)
from byceps.services.netsession_tourney.forms import MatchResultForm
from byceps.services.netsession_tourney.match_queries import (
    get_match_slots,
    get_matches_for_tournament,
)
from byceps.services.netsession_tourney.result_service import report_result
from byceps.services.netsession_tourney.tournament_queries import (
    get_stages_for_tournament,
)
from byceps.services.party.models import PartyID
from byceps.util.framework.flash import flash_error, flash_success
from byceps.util.result import Err, Ok, Result


def find_match(party_id: PartyID, tournament_id: Any, match_id: Any) -> Any:
    """Return the match of the tournament, or `None`."""
    matches = get_matches_for_tournament(party_id, tournament_id)
    return next((item for item in matches if item.id == match_id), None)


def get_match_stage(party_id: PartyID, tournament_id: Any, match: Any) -> Any:
    """Return the stage of the match, or `None`."""
    stages_by_id = {
        stage.id: stage
        for stage in get_stages_for_tournament(party_id, tournament_id)
    }
    return stages_by_id.get(match.stage_id)


def is_ffa_result_stage(stage: Any) -> bool:
    """Return true if the stage takes an FFA result form."""
    return stage is not None and is_ffa_result_stage_type(stage.type)


def _report_admin_result(
    party_id: PartyID,
    tournament_id: Any,
    match_id: Any,
    idempotency_key: str,
    winner_slot: Any,
    score: Any,
    ranking: Any,
    comment: str | None,
) -> None:
    match report_result(
        party_id,
        tournament_id,
        match_id,
        g.user.id,
        idempotency_key=idempotency_key,
        winner_slot=winner_slot,
        score=score,
        ranking=ranking,
        actor_is_admin_or_referee=True,
        admin_comment=comment,
        reason_code='admin_override',
        correlation_id=request.headers.get('X-Correlation-ID'),
    ):
        case Ok(_):
            flash_success(gettext('Ergebnis wurde gespeichert.'))
        case Err(message):
            flash_error(message)


def _parse_ffa_result(stage: Any, slots: list[Any]) -> Result:
    return (
        parse_admin_flatout2_result_form(request.form, slots)
        if is_flatout2_stage_type(stage.type)
        else parse_admin_ffa_result_form(
            request.form,
            slots,
            placement_points_rules=stage.settings.get(
                'placement_points_rules', []
            ),
        )
    )


def set_ffa_result(
    party_id: PartyID, tournament_id: Any, match_id: Any, match: Any, stage: Any
) -> Any:
    """Store the FFA result of the form; return the redirect."""
    slots = sorted(
        get_match_slots({match.id}).get(match.id, []),
        key=lambda slot: slot.slot_no,
    )
    parsed_ffa_result = _parse_ffa_result(stage, slots)
    if parsed_ffa_result.is_err():
        flash_error(parsed_ffa_result.unwrap_err())
        return redirect_to_match_or_tournament_view(
            party_id, tournament_id, match_id
        )

    winner_slot, score, ranking, comment = parsed_ffa_result.unwrap()
    idempotency_key = get_or_create_idempotency_key(
        request.form.get('idempotency_key')
    )
    _report_admin_result(
        party_id,
        tournament_id,
        match_id,
        idempotency_key,
        winner_slot,
        score,
        ranking,
        comment,
    )
    return redirect_to_match_or_tournament_view(
        party_id, tournament_id, match_id
    )


def _get_two_slot_form_error(form: MatchResultForm) -> str | None:
    if not form.validate():
        return gettext('Ungültige Ergebnisdaten.')
    if form.slot_1_points.data == form.slot_2_points.data:
        return gettext(
            'Gleichstände sind bei der manuellen Ergebniserfassung nicht erlaubt.'
        )
    return None


def set_two_slot_result(
    party_id: PartyID, tournament_id: Any, match_id: Any
) -> Any:
    """Store the two-slot result of the form; return the redirect."""
    form = MatchResultForm(request.form)
    error = _get_two_slot_form_error(form)
    if error is not None:
        flash_error(error)
        return redirect_to_match_or_tournament_view(
            party_id, tournament_id, match_id
        )

    winner_slot = 1 if form.slot_1_points.data > form.slot_2_points.data else 2
    score = build_score_payload(
        f'{form.slot_1_points.data}:{form.slot_2_points.data}'
    )
    ranking: dict = {}
    idempotency_key = get_or_create_idempotency_key(form.idempotency_key.data)
    comment = stripped_or_none(form.comment.data)
    _report_admin_result(
        party_id,
        tournament_id,
        match_id,
        idempotency_key,
        winner_slot,
        score,
        ranking,
        comment,
    )
    return redirect_to_match_or_tournament_view(
        party_id, tournament_id, match_id
    )
