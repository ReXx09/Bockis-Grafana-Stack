"""Raspberry Pi dashboard definition."""

from ..dashboard import host_dashboard_json


def dashboard(bucket: str) -> str:
    return host_dashboard_json(
        bucket,
        "bocki-raspberry",
        "Bocki Raspberry",
        "r.host =~ /^raspi/",
        include_temperature=True,
    )
