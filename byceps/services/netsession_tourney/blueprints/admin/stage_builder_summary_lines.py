"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_summary_lines
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Text lines that describe stages of the stage builder (Turnierplaner):
the meta box of a stage and the summary shown before generating it (see
`stage_builder_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from flask_babel import gettext

from byceps.services.netsession_tourney.models import Stage


# group summaries


def format_group_distribution_summary(group_sizes: list[int]) -> str:
    if not group_sizes:
        return gettext('Keine Gruppenverteilung verfügbar.')

    counts_by_size: dict[int, int] = {}
    for size in group_sizes:
        counts_by_size[size] = counts_by_size.get(size, 0) + 1

    parts = [
        gettext('%(count)s Gruppen à %(size)s', count=count, size=size)
        for size, count in sorted(counts_by_size.items(), reverse=True)
    ]
    return gettext('Konkrete Verteilung: %(parts)s', parts=', '.join(parts))


def format_round_robin_global_round_summary(
    group_sizes: list[int],
) -> str | None:
    if not group_sizes:
        return None

    matches_by_round = _count_matches_by_round(group_sizes)
    if not matches_by_round:
        return None

    parts = [
        gettext(
            'Runde %(round_no)s: %(match_count)s Matches',
            round_no=round_index + 1,
            match_count=match_count,
        )
        for round_index, match_count in enumerate(matches_by_round)
    ]
    return gettext('Globale Rundensicht: %(parts)s', parts=', '.join(parts))


def _count_matches_by_round(group_sizes: list[int]) -> list[int]:
    matches_by_round: list[int] = []
    for group_size in group_sizes:
        round_count = (
            group_size if group_size % 2 == 1 else max(1, group_size - 1)
        )
        matches_per_round = group_size // 2
        for round_index in range(round_count):
            if round_index >= len(matches_by_round):
                matches_by_round.append(0)
            matches_by_round[round_index] += matches_per_round
    return matches_by_round


def build_group_size_summary_lines(group_sizes: list[int]) -> list[str]:
    lines = [format_group_distribution_summary(group_sizes)]
    round_summary = format_round_robin_global_round_summary(group_sizes)
    if round_summary is not None:
        lines.append(round_summary)
    return lines


def get_round_robin_builder_mode(stage: Stage, settings: dict):
    return settings.get('builder_round_robin_mode') or (
        stage.settings or {}
    ).get('builder_round_robin_mode')


def get_round_robin_strategy_line(round_robin_builder_mode) -> str:
    if round_robin_builder_mode == 'manual_group_count':
        return gettext('Strategie: Expertenoption mit manueller Gruppenzahl')

    return gettext(
        'Strategie: Empfohlener Standard, bevorzugt 8 Gruppen / Top 2 bei einem Hauptturnier mit 16 Plätzen'
    )


def get_group_materialization_line() -> str:
    return gettext(
        'Beim Erzeugen werden daraus echte Gruppenphasen wie "Vorrunde Gruppe A", "Vorrunde Gruppe B" usw.'
    )


def get_group_qualification_line(qualifiers_per_group, main_stage_size) -> str:
    return gettext(
        'Qualifikation: Top %(top_n)s pro Gruppe -> %(size)s für das Hauptturnier',
        top_n=qualifiers_per_group,
        size=main_stage_size,
    )
