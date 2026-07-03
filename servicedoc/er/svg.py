from __future__ import annotations

import logging

import plantuml

logger = logging.getLogger(__name__)

DEFAULT_PLANTUML_SERVER = "http://www.plantuml.com/plantuml/svg/"


def render_svg(plantuml_text: str, server_url: str = DEFAULT_PLANTUML_SERVER) -> str | None:
    """Render PlantUML source to an SVG string via a PlantUML server.

    Sends the diagram source to `server_url` (defaults to the public
    plantuml.com server) — point this at a self-hosted instance via
    ServiceDocConfig.plantuml_server_url if the schema shouldn't leave the
    network. Returns None on any failure (network, server error, or the
    `plantuml` 0.2.1 client's own bug where it raises AttributeError on
    `.message` instead of surfacing the real HTTP error) so callers can fall
    back to the plain PlantUML code block.
    """
    try:
        data = plantuml.PlantUML(url=server_url).processes(plantuml_text)
    except Exception as exc:
        logger.warning("PlantUML SVG render failed (%s): %s", type(exc).__name__, exc)
        return None
    try:
        return data.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        logger.warning("PlantUML server returned non-SVG/non-UTF-8 data")
        return None
