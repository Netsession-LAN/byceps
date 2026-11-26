"""
byceps.services.netsession_tourney.ffa_stage_builder_validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Validation of the FFA stage builder settings.
"""

from __future__ import annotations

from byceps.util.result import Err, Ok, Result

from .models import (
    StageType,
)
from .stage_builder_settings import (
    STAGE_BUILDER_MAIN_STAGE_SIZES,
)


def validate_ffa_stage_builder_settings(
    *,
    main_stage_type: StageType,
    main_stage_size: int,
    max_players_per_match: int | None,
    preliminary_type: StageType | None,
    generation_basis: str,
) -> Result[None, str]:
    error = _check_ffa_stage_builder_structure(
        main_stage_type=main_stage_type,
        main_stage_size=main_stage_size,
        preliminary_type=preliminary_type,
        generation_basis=generation_basis,
    )
    if error is not None:
        return Err(error)

    error = _check_ffa_stage_builder_max_players(
        main_stage_type=main_stage_type,
        preliminary_type=preliminary_type,
        max_players_per_match=max_players_per_match,
    )
    if error is not None:
        return Err(error)

    return Ok(None)


_ALLOWED_FFA_STAGE_BUILDER_STAGE_TYPES = {
    StageType.ffa_single_elimination,
    StageType.ffa_flatout2_single_elimination,
}


def _check_ffa_stage_builder_structure(
    *,
    main_stage_type: StageType,
    main_stage_size: int,
    preliminary_type: StageType | None,
    generation_basis: str,
) -> str | None:
    allowed_ffa_stage_types = _ALLOWED_FFA_STAGE_BUILDER_STAGE_TYPES
    if main_stage_type not in allowed_ffa_stage_types:
        return 'Dieser Typ des Hauptturniers wird vom FFA-Baukasten nicht unterstützt.'

    if main_stage_size not in STAGE_BUILDER_MAIN_STAGE_SIZES:
        return 'Ungültige Größe des Hauptturniers.'

    if generation_basis != 'ready':
        return 'Ungültige Grundlage für die Erzeugung.'

    if (
        preliminary_type is not None
        and preliminary_type not in allowed_ffa_stage_types
    ):
        return 'Dieser Vorrunden-Typ wird vom FFA-Baukasten nicht unterstützt.'

    return None


def _check_ffa_stage_builder_max_players(
    *,
    main_stage_type: StageType,
    preliminary_type: StageType | None,
    max_players_per_match: int | None,
) -> str | None:
    if max_players_per_match is None:
        return 'Für den FFA-Baukasten bitte die maximale Spielerzahl pro Match angeben.'

    if max_players_per_match < 2 or max_players_per_match > 64:
        return 'Ungültige maximale Spielerzahl pro Match.'

    if _has_invalid_flatout2_heat_size(main_stage_type, max_players_per_match):
        return 'FlatOut 2 braucht 6 bis 8 Spieler pro Match.'

    if _has_invalid_flatout2_heat_size(preliminary_type, max_players_per_match):
        return 'FlatOut 2 braucht 6 bis 8 Spieler pro Match.'

    return None


def _has_invalid_flatout2_heat_size(
    stage_type: StageType | None, max_players_per_match: int
) -> bool:
    return stage_type == StageType.ffa_flatout2_single_elimination and (
        max_players_per_match < 6 or max_players_per_match > 8
    )
