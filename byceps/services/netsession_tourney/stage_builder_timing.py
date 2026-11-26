"""
byceps.services.netsession_tourney.stage_builder_timing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Timing of the stages created by the stage builder.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class StageTiming:
    match_duration_minutes: int | None
    max_matches_per_round: int | None
    break_between_rounds_minutes: int | None

    def validate(self) -> str | None:
        if self.match_duration_minutes is not None and not (
            1 <= self.match_duration_minutes <= 240
        ):
            return 'Ungültige Matchdauer.'
        if self.max_matches_per_round is not None and not (
            1 <= self.max_matches_per_round <= 256
        ):
            return 'Ungültige Höchstzahl an Matches pro Runde.'
        if self.break_between_rounds_minutes is not None and not (
            0 <= self.break_between_rounds_minutes <= 240
        ):
            return 'Ungültige Pause zwischen den Runden.'
        return None

    def settings(self) -> dict[str, int]:
        """Only the values that were given."""
        values = {
            'match_duration_minutes': self.match_duration_minutes,
            'max_matches_per_round': self.max_matches_per_round,
            'break_between_rounds_minutes': self.break_between_rounds_minutes,
        }
        return {
            key: value for key, value in values.items() if value is not None
        }
