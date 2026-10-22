#!/usr/bin/env python3
"""Write mcp-server/src/integration-tables.json from the integration's own tables.

    python scripts/render_mcp_tables.py

The MCP server cannot import the integration, but it must refuse and accept exactly what the
integration does (which domains a pump, valve or sensor mapping may be, which probe units are
read). tests/test_mcp_tables.py fails when the committed file is not what this writes. Edit the
integration's tables, never the JSON.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TARGET = ROOT / "mcp-server" / "src" / "integration-tables.json"


def tables():
    from custom_components.crop_steering import setup_api

    return {
        "actuator_domains": sorted(setup_api.ACTUATOR_DOMAINS),
        "hardware_domains": {
            key: sorted(domains) for key, domains in setup_api.HARDWARE_DOMAINS.items()
        },
        "sensor_kinds": dict(setup_api.SENSOR_KINDS),
        "units": {
            kind: sorted(accepted) for kind, accepted in setup_api.UNITS.items()
        },
    }


def render():
    return json.dumps(tables(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    TARGET.write_text(render(), encoding="utf-8", newline="\n")
