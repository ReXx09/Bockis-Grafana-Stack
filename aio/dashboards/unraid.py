"""Unraid dashboard definition."""

from ..dashboard import host_dashboard_json


def dashboard(bucket: str) -> str:
    return host_dashboard_json(
        bucket,
        "bocki-unraid-v2",
        "Bocki Unraid",
        'r.host == "bocki-aio"',
        include_docker=True,
    )
