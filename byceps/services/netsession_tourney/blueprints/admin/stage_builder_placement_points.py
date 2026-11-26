"""
byceps.services.netsession_tourney.blueprints.admin.stage_builder_placement_points
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The placement-to-points scheme of FFA stages as entered in the stage
form, one rule per line (see `stage_builder_helpers`).

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

import re

from flask_babel import gettext

from byceps.util.result import Err, Ok, Result


PLACEMENT_POINTS_LINE_PATTERN = re.compile(
    r'^(?:platz\s*#?\s*)?(\d+)(?:\s*-\s*(\d+))?\s*(?:=|:|->)?\s*(\d+)\s*(?:punkte?|pts?)?$',
    re.IGNORECASE,
)


def parse_ffa_placement_points_text(
    raw_text: str | None,
) -> Result[list[dict], str]:
    normalized_text = (raw_text or '').strip()
    if not normalized_text:
        return Err(
            gettext(
                'Bitte für dieses FFA-Format ein Platz-zu-Punkte-Schema angeben.'
            )
        )

    rules_result = _parse_lines(normalized_text)
    if rules_result.is_err():
        return rules_result

    rules = rules_result.unwrap()
    if not rules:
        return Err(
            gettext(
                'Bitte für dieses FFA-Format mindestens eine Platz-zu-Punkte-Regel angeben.'
            )
        )

    rules.sort(key=lambda item: (item['from_place'], item['to_place']))

    if _have_overlapping_places(rules):
        return Err(
            gettext('Platzbereiche im FFA-Schema dürfen sich nicht überlappen.')
        )

    return Ok(rules)


def _parse_lines(normalized_text: str) -> Result[list[dict], str]:
    rules = []
    for line_no, raw_line in enumerate(normalized_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        rule_result = _parse_line(line, line_no)
        if rule_result.is_err():
            return Err(rule_result.unwrap_err())

        rules.append(rule_result.unwrap())

    return Ok(rules)


def _parse_line(line: str, line_no: int) -> Result[dict, str]:
    match = PLACEMENT_POINTS_LINE_PATTERN.fullmatch(line)
    if match is None:
        return Err(
            gettext(
                'Ungültiges Platz-zu-Punkte-Schema in Zeile %(line_no)s.',
                line_no=line_no,
            )
        )

    from_place = int(match.group(1))
    to_place = int(match.group(2) or match.group(1))
    points = int(match.group(3))

    error = _get_rule_error(from_place, to_place, points, line_no)
    if error is not None:
        return Err(error)

    return Ok(
        {
            'from_place': from_place,
            'to_place': to_place,
            'points': points,
        }
    )


def _get_rule_error(
    from_place: int, to_place: int, points: int, line_no: int
) -> str | None:
    if from_place < 1 or to_place < 1:
        return gettext(
            'Plätze müssen in Zeile %(line_no)s bei 1 oder höher liegen.',
            line_no=line_no,
        )
    if to_place < from_place:
        return gettext(
            'Der Platzbereich in Zeile %(line_no)s ist ungültig.',
            line_no=line_no,
        )
    if points < 0 or points > 999:
        return gettext(
            'Die Punkte in Zeile %(line_no)s müssen zwischen 0 und 999 liegen.',
            line_no=line_no,
        )
    return None


def _have_overlapping_places(sorted_rules: list[dict]) -> bool:
    previous_to_place = 0
    for rule in sorted_rules:
        if rule['from_place'] <= previous_to_place:
            return True
        previous_to_place = rule['to_place']
    return False


def get_max_rule_place(placement_points_text: str | None) -> int:
    """Return the highest place covered by the scheme, 0 if it is invalid
    or empty."""
    parsed_rules_result = parse_ffa_placement_points_text(placement_points_text)
    if parsed_rules_result.is_err():
        return 0

    rules = parsed_rules_result.unwrap()
    if not rules:
        return 0

    return max(int(rule['to_place']) for rule in rules)


def get_first_positive_int(candidates: list) -> int | None:
    for candidate in candidates:
        try:
            parsed = int(candidate)
        except TypeError, ValueError:
            continue
        if parsed > 0:
            return parsed

    return None
