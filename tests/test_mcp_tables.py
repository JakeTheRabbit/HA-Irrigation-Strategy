"""The MCP server's mapping tables are the integration's, not a copy that can drift.

The MCP server (mcp-server/) previews a setup change locally before Home Assistant sees it. A table
there that is narrower than the integration's refuses a mapping the integration and controller
accept (a pump on an input_boolean, a valve entity, a probe in uS/cm); a wider one previews a save
Home Assistant then refuses. The server reads mcp-server/src/integration-tables.json, which
scripts/render_mcp_tables.py writes from setup_api's own tables.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_mcp_tables  # noqa: E402

COMMITTED = ROOT / "mcp-server" / "src" / "integration-tables.json"


def test_the_committed_table_is_what_the_integration_writes():
    assert COMMITTED.read_text(encoding="utf-8") == render_mcp_tables.render(), (
        "mcp-server/src/integration-tables.json is stale: "
        "run python scripts/render_mcp_tables.py"
    )


def test_pumps_and_valves_may_be_anything_the_controller_can_switch():
    tables = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert tables["actuator_domains"] == ["input_boolean", "switch", "valve"]
    for key in ("pump_switch", "main_line_switch"):
        assert tables["hardware_domains"][key] == tables["actuator_domains"]


def test_probe_units_include_the_ones_the_integration_converts():
    units = json.loads(COMMITTED.read_text(encoding="utf-8"))["units"]
    assert {"%", "m3/m3", "m³/m³"} <= set(units["vwc"])
    assert {"ms/cm", "ds/m", "us/cm", "µs/cm", "μs/cm"} <= set(units["ec"])
