"""Reference-style overview dashboard built from the available metrics."""

import json

from ..dashboard import (
    cpu_core_temperature_panel,
    cpu_core_usage_panel,
    dashboard_section,
    dashboard_switch_links,
    flatten_dashboard_sections,
    loki_logs,
    loki_stat,
    loki_timeseries,
    network_rate_panel,
    percentage_gauge_panel,
    smart_temperature_panel,
    system_stat,
    system_table,
    system_timeseries,
    uptime_kuma_section,
)


def dashboard(bucket: str, include_uptime_kuma: bool = False) -> str:
    unraid_host = 'r.host == "bocki-aio"'
    sections = [
        dashboard_section(1, "Status", [
            percentage_gauge_panel(101, "CPU LAST", 0, 0, bucket, "cpu", "usage_active", 'r.cpu == "cpu-total"', unraid_host),
            percentage_gauge_panel(102, "RAM", 6, 0, bucket, "mem", "used_percent", host_filter=unraid_host),
            system_stat(103, "LAUFENDE DOCKER", 12, 0, bucket, "docker", "n_containers_running", host_filter=unraid_host),
            system_stat(104, "UPTIME", 18, 0, bucket, "system", "uptime", host_filter=unraid_host),
        ]),
        dashboard_section(2, "Server Hardware", [
            system_timeseries(201, "CPU TEMPERATUR", 0, 0, bucket, "temp", "temp", group_by="name", host_filter=unraid_host),
            cpu_core_usage_panel(202, "PROZESSORAUSLASTUNG PRO THREAD", 12, 0, bucket, unraid_host),
            cpu_core_temperature_panel(203, "CPU-KERN-TEMPERATUREN", 0, 10, bucket, unraid_host),
            system_timeseries(204, "SPEICHERAUSLASTUNG", 12, 10, bucket, "mem", "used_percent", host_filter=unraid_host),
        ]),
        dashboard_section(3, "Array und SMART", [
            system_timeseries(301, "FESTPLATTENBELEGUNG", 0, 0, bucket, "disk", "used_percent", group_by="path", host_filter=unraid_host),
            smart_temperature_panel(302, "HDD TEMPERATURE", 12, 0, bucket, unraid_host),
            system_table(303, "SMART STATUS", 0, 10, bucket, "smart_device", "health_ok", group_by="device", host_filter=unraid_host),
        ]),
        dashboard_section(4, "Netzwerk", [
            network_rate_panel(401, "DOWNLOAD", 0, 0, bucket, "bytes_recv", unraid_host),
            network_rate_panel(402, "UPLOAD", 12, 0, bucket, "bytes_sent", unraid_host),
        ]),
        dashboard_section(5, "Firewall", [
            loki_stat(501, "FIREWALL GEBLOCKT", "action=\"block\"", "red"),
            loki_stat(502, "FIREWALL ERLAUBT", "action=\"pass\"", "green"),
            loki_timeseries(503, "PASS / BLOCK ZEITVERLAUF", 0, 8),
            loki_logs(504, "FIREWALL EREIGNISSE", 12, 8),
        ]),
        dashboard_section(6, "Docker", [
            system_timeseries(601, "DOCKER CPU AUSLASTUNG", 0, 0, bucket, "docker_container_cpu", "usage_percent", group_by="container_name", host_filter=unraid_host),
            system_table(602, "DOCKER RAMVERBRAUCH", 12, 0, bucket, "docker_container_mem", "usage", group_by="container_name", host_filter=unraid_host),
        ]),
    ]
    if include_uptime_kuma:
        sections.append(uptime_kuma_section(bucket))
    payload = {
        "uid": "bocki-all-in-one-v2",
        "title": "Bocki Gesamtuebersicht",
        "tags": ["bocki", "overview", "unraid", "firewall", "system"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "links": dashboard_switch_links(),
        "panels": flatten_dashboard_sections(sections),
    }
    return json.dumps(payload, indent=2) + "\n"
