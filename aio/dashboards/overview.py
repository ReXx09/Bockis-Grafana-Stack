"""Bocki overview dashboard definition."""

from ..dashboard import unified_dashboard_json


def dashboard(bucket: str, include_uptime_kuma: bool = False) -> str:
    return unified_dashboard_json(
        bucket,
        include_uptime_kuma,
        uid="bocki-all-in-one-v2",
        title="Bocki Gesamtuebersicht",
    )
