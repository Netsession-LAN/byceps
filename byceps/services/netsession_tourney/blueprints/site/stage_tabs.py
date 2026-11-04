"""
byceps.services.netsession_tourney.blueprints.site.stage_tabs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tabs to switch between the stages of a tournament page.
"""

from flask import url_for


def build_stage_tab_rows(endpoint, slug, sections, selected) -> list[dict]:
    """Return one tab per section; `selected` is the current section."""
    selected_key = selected['key'] if selected is not None else None
    return [
        {
            'title': section['title'],
            'url': url_for(endpoint, slug=slug, stage=section['key']),
            'is_current': section['key'] == selected_key,
        }
        for section in sections
    ]
