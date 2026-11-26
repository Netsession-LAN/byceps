"""
byceps.services.netsession_tourney.blueprints.site.common_navigation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Which main navigation item and sub navigation menu belong to the
tournament pages.

:Copyright: 2014-2026 Jochen Kupperschmidt
:License: Revised BSD (see `LICENSE` file for details)
"""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from flask import (
    g,
    url_for,
)
from flask_babel import get_locale

from byceps.services.site_navigation import site_navigation_service
from byceps.services.site_navigation.models import NavItem, NavItemTargetType
from byceps.util.l10n import get_default_locale


def get_main_nav_current_page_id() -> str:
    """Return the `current_page_id` configured for the NS tourney main-nav item."""
    site = getattr(g, 'site', None)
    if site is None:
        return 'ns_tourney_index'

    locale = get_locale()
    if locale is None:
        return 'ns_tourney_index'

    language_codes = [locale.language]

    default_locale = get_default_locale()
    if default_locale.language not in language_codes:
        language_codes.append(default_locale.language)

    for language_code in language_codes:
        items = site_navigation_service.get_items_for_menu(
            site.id, 'main', language_code
        )
        item_current_page_id = _find_main_nav_item_current_page_id(items)
        if item_current_page_id is not None:
            return item_current_page_id

    return 'ns_tourney_index'


def find_netsession_tourney_subnav_menu_id(*view_names: str) -> UUID | None:
    site = getattr(g, 'site', None)
    if site is None:
        return None

    locale = get_locale()
    if locale is None:
        return None

    language_codes = [locale.language]

    default_locale = get_default_locale()
    if default_locale.language not in language_codes:
        language_codes.append(default_locale.language)

    for language_code in language_codes:
        for view_name in view_names:
            menu_id = site_navigation_service.find_submenu_id_for_view(
                site.id, language_code, view_name
            )
            if menu_id is not None:
                return menu_id

    return None


def _strip_trailing_slash(path: str) -> str:
    return path.rstrip('/') if path != '/' else '/'


def _get_nav_target_path(target: str) -> str:
    target_path = urlsplit(target).path if '://' in target else target
    if target_path and not target_path.startswith('/'):
        target_path = '/' + target_path
    return target_path


def _is_ns_tourney_endpoint_nav_item(item: NavItem) -> bool:
    return (
        item.target_type == NavItemTargetType.endpoint
        and item.target == 'netsession_tourney.index'
    )


def _is_ns_tourney_url_nav_item(item: NavItem, ns_tourney_prefix: str) -> bool:
    if item.target_type != NavItemTargetType.url:
        return False

    target = item.target.strip()
    if not target:
        return False

    target_path = _get_nav_target_path(target)
    return _strip_trailing_slash(target_path) == ns_tourney_prefix


def _find_main_nav_item_current_page_id(items: list[NavItem]) -> str | None:
    ns_tourney_index_url = url_for('netsession_tourney.index')
    ns_tourney_prefix = _strip_trailing_slash(ns_tourney_index_url)

    for item in items:
        if _is_ns_tourney_endpoint_nav_item(item):
            return item.current_page_id

        if _is_ns_tourney_url_nav_item(item, ns_tourney_prefix):
            return item.current_page_id

    return None
