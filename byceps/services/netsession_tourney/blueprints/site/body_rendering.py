"""
byceps.services.netsession_tourney.blueprints.site.body_rendering
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Render rule template and prize texts (Markdown or HTML) for the public
site. The result is sanitized: only harmless markup (headings, lists,
tables, links, images, …) survives; scripts, event handler attributes and
`javascript:` URLs are removed.
"""

from __future__ import annotations

from markupsafe import Markup
import mistletoe
import nh3

from ...models import RuleTemplateBodyFormat


def render_formatted_body_html(
    body: str, body_format: RuleTemplateBodyFormat
) -> Markup:
    if body_format == RuleTemplateBodyFormat.markdown:
        html = mistletoe.markdown(body)
    else:
        html = body

    # Safe: `nh3` has removed scripts, event handlers and `javascript:` URLs.
    sanitized_html = nh3.clean(html, link_rel='noopener noreferrer')
    return Markup(sanitized_html)  # noqa: S704  # nosec B704
