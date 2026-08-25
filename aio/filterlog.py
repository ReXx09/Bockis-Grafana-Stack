"""Parser for the comma-separated OPNsense/PF filterlog payload."""

from __future__ import annotations

import csv
import io
import ipaddress
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FirewallEvent:
    action: str
    direction: str
    interface: str
    family: str
    protocol: str
    source_ip: str
    destination_ip: str
    source_port: int | None = None
    destination_port: int | None = None
    source_country: str | None = None
    source_latitude: float | None = None
    source_longitude: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FilterlogParseError(ValueError):
    pass


def parse_filterlog(message: str) -> FirewallEvent:
    payload = message.split("filterlog:", 1)[-1].strip() if "filterlog:" in message else message.strip()
    fields = next(csv.reader(io.StringIO(payload)))
    if len(fields) < 19:
        raise FilterlogParseError(f"Zu wenige filterlog-Felder: {len(fields)}")

    # OPNsense filterlog positions follow the PF CSV format.
    action = fields[6].strip().lower()
    if action not in {"pass", "block", "reject", "match", "nat", "rdr"}:
        raise FilterlogParseError(f"Unbekannte Firewall-Aktion: {action or '<leer>'}")
    family = {"4": "ipv4", "6": "ipv6"}.get(fields[8].strip(), fields[8].strip() or "unknown")
    protocol = fields[16].strip().lower() or fields[15].strip().lower() or "unknown"
    source_ip = fields[18].strip()
    destination_ip = fields[19].strip() if len(fields) > 19 else ""
    validate_ip(source_ip)
    validate_ip(destination_ip)
    source_port = parse_port(fields[20] if len(fields) > 20 else "")
    destination_port = parse_port(fields[21] if len(fields) > 21 else "")
    return FirewallEvent(
        action=action,
        direction=fields[7].strip().lower() or "unknown",
        interface=fields[4].strip() or "unknown",
        family=family,
        protocol=protocol,
        source_ip=source_ip,
        destination_ip=destination_ip,
        source_port=source_port,
        destination_port=destination_port,
    )


def validate_ip(value: str) -> None:
    try:
        ipaddress.ip_address(value)
    except ValueError as error:
        raise FilterlogParseError(f"Ungueltige IP-Adresse: {value or '<leer>'}") from error


def parse_port(value: str) -> int | None:
    value = value.strip()
    if not value or value == "-":
        return None
    try:
        port = int(value)
    except ValueError as error:
        raise FilterlogParseError(f"Ungueltiger Port: {value}") from error
    if not 0 <= port <= 65535:
        raise FilterlogParseError(f"Port ausserhalb des Bereichs: {port}")
    return port
