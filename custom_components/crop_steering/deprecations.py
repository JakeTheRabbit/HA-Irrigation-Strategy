"""Deprecated services and entities: say so once, in Repairs, and keep them working.

A deprecated service or select still does what it did. The first time one is used in a Home
Assistant run, this raises a Repairs notice that names what to use instead, and every use
writes a warning to the log. Nothing is removed here: the planned removal is in the changelog.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, REPAIRS_DOCS_URL

_LOGGER = logging.getLogger(__name__)

# The release that removes the deprecated items. Also stated in CHANGELOG.md.
REMOVAL_RELEASE = "4.0.0"


def note_deprecated(hass: HomeAssistant, key: str, what: str, instead: str) -> None:
    """Warn in the log, and raise the Repairs notice for `key` the first time it is used."""
    _LOGGER.warning(
        "crop_steering: %s is deprecated and will be removed in %s. %s",
        what,
        REMOVAL_RELEASE,
        instead,
    )
    seen = hass.data.setdefault(DOMAIN, {}).setdefault("_deprecations_noted", set())
    if key in seen:
        return
    seen.add(key)
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"deprecated_{key}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="deprecated_feature",
        translation_placeholders={
            "what": what,
            "instead": instead,
            "removal": REMOVAL_RELEASE,
        },
        learn_more_url=REPAIRS_DOCS_URL,
    )
