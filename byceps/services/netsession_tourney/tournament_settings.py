"""
byceps.services.netsession_tourney.tournament_settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Checks and changes of tournament settings shared by creating and updating
a tournament.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from byceps.database import db
from byceps.util.result import Err, Ok, Result

from .coin_service import _validate_coin_cost
from .dbmodels import DbNetsessionTourneyParticipant, DbNetsessionTourneyTournament
from .models import RegistrationMode, TournamentMode, TournamentStatus
from .participant_state import _validate_participant_limit
from .registration_validation import (
    _validate_mode_for_registration_mode,
    _validate_substitute_count_for_registration_mode,
    _validate_team_size_for_registration_mode,
)
from .stage_activation import _delete_all_stages_for_tournament
from .tournament_queries import ACTIVE_PARTICIPANT_STATUS_VALUES


def validate_tournament_settings(
    *,
    mode: TournamentMode,
    registration_mode: RegistrationMode,
    team_size: int | None,
    substitute_count: int | None,
    participant_limit: int | None,
    coin_cost: int,
) -> str | None:
    """Return an error message, or `None` if the settings are fine."""
    for result in (
        _validate_mode_for_registration_mode(
            mode=mode, registration_mode=registration_mode
        ),
        _validate_team_size_for_registration_mode(
            registration_mode=registration_mode, team_size=team_size
        ),
        _validate_substitute_count_for_registration_mode(
            registration_mode=registration_mode, substitute_count=substitute_count
        ),
        _validate_participant_limit(participant_limit),
        _validate_coin_cost(coin_cost),
    ):
        if result.is_err():
            return result.unwrap_err()
    return None


def clean_text(value: str | None) -> str | None:
    """Stripped text, or `None` for nothing."""
    return value.strip() if value else None


def sponsor_logo_url_if_sponsored(
    is_sponsored: bool, sponsor_logo_url: str | None
) -> str | None:
    return sponsor_logo_url.strip() if is_sponsored and sponsor_logo_url else None


@dataclass(frozen=True)
class ModeChanges:
    mode_changed: bool
    registration_mode_changed: bool
    deleted_stage_count: int


def apply_mode_changes(
    db_tournament: DbNetsessionTourneyTournament,
    mode: TournamentMode,
    registration_mode: RegistrationMode,
) -> Result[ModeChanges, str]:
    """Change the tournament mode (deletes the stages) and the registration
    mode; both only in draft, the latter only without active participants."""
    mode_changed = db_tournament.mode != mode.value
    registration_mode_changed = (
        db_tournament.registration_mode != registration_mode.value
    )
    is_draft = db_tournament.status == TournamentStatus.draft.value

    deleted_stage_count = 0
    if mode_changed:
        if not is_draft:
            return Err('Der Turniermodus lässt sich nur im Entwurf ändern.')
        deleted_stage_count = _delete_all_stages_for_tournament(db_tournament.id)
        db_tournament.mode = mode.value

    if registration_mode_changed:
        if not is_draft:
            return Err('Der Anmeldemodus lässt sich nur im Entwurf ändern.')
        if _has_active_participants(db_tournament.id):
            return Err(
                'Der Anmeldemodus lässt sich nur ändern, solange es keine '
                'aktiven Teilnehmer gibt.'
            )
        db_tournament.registration_mode = registration_mode.value

    return Ok(
        ModeChanges(mode_changed, registration_mode_changed, deleted_stage_count)
    )


def _has_active_participants(tournament_id) -> bool:
    return bool(
        db.session.scalar(
            select(db.func.count(DbNetsessionTourneyParticipant.id))
            .filter_by(tournament_id=tournament_id)
            .filter(
                DbNetsessionTourneyParticipant.status.in_(
                    ACTIVE_PARTICIPANT_STATUS_VALUES
                )
            )
        )
    )
