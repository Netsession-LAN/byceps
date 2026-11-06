"""
byceps.services.netsession_tourney.team_logo_uploads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Team logos uploaded by players. The permission is checked *before* the file
is stored, so nobody can drop files on the server through a team form they
are not allowed to use.
"""

from __future__ import annotations

from typing import BinaryIO

from byceps.services.party.models import PartyID
from byceps.services.user.models import User
from byceps.util.result import Err, Result

from .logo_service import upload_logo_image
from .models import ParticipantID, RegistrationMode, Tournament, TournamentID
from .team_captain_service import find_managed_team_for_user
from .tourney_registration_checks import validate_user_can_enter_tournament


def upload_logo_for_new_team(
    party_id: PartyID,
    tournament: Tournament,
    user: User,
    stream: BinaryIO,
    *,
    label: str,
    original_filename: str,
) -> Result[str, str]:
    if tournament.registration_mode == RegistrationMode.solo:
        return Err('Dieses Turnier erlaubt nur Solo-Anmeldungen.')
    entry_error = validate_user_can_enter_tournament(
        party_id, tournament.id, tournament, user.id, check_capacity=True
    )
    if entry_error is not None:
        return Err(entry_error)
    return upload_logo_image(
        party_id, user, stream, label=label, original_filename=original_filename
    )


def upload_logo_for_managed_team(
    party_id: PartyID,
    tournament_id: TournamentID,
    participant_id: ParticipantID,
    user: User,
    stream: BinaryIO,
    *,
    label: str,
    original_filename: str,
) -> Result[str, str]:
    team = find_managed_team_for_user(party_id, tournament_id, user.id)
    if team is None or team.id != participant_id:
        return Err('Team nicht gefunden, oder du darfst es nicht verwalten.')
    return upload_logo_image(
        party_id, user, stream, label=label, original_filename=original_filename
    )
