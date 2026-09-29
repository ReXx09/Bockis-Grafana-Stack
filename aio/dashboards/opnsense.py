"""Combined OPNsense host and firewall dashboard definition."""

import json
from typing import Any

from ..dashboard import dashboard_json, host_dashboard_json


def _renumber(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    next_id = 1
    result = []
    for panel in panels:
        updated = dict(panel)
        updated["id"] = next_id
        next_id += 1
        result.append(updated)
    return result


def dashboard(bucket: str) -> str:
    firewall = json.loads(dashboard_json())
    host = json.loads(host_dashboard_json(bucket, "bocki-opnsense-v2", "Bocki OPNsense", 'r.host == "opnsense"'))
    combined = dict(host)
    combined["uid"] = "bocki-opnsense-v2"
    combined["title"] = "Bocki OPNsense"
    combined["tags"] = ["bocki", "opnsense", "firewall", "telegraf"]
    combined["panels"] = _renumber(host["panels"] + firewall["panels"])
    return json.dumps(combined, indent=2) + "\n"
