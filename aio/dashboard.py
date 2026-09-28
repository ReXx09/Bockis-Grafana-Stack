"""Provisioned Grafana dashboard definition for the firewall metrics contract."""

from __future__ import annotations

import json
from typing import Any


def dashboard_json() -> str:
    panels: list[dict[str, Any]] = [
        stat_panel(1, "Geblockte Ereignisse", "block", 0, 0),
        stat_panel(2, "Erlaubte Ereignisse", "pass", 6, 0),
        timeseries_panel(3, "Pass / Block im Zeitverlauf", 12, 0),
        table_panel(4, "Top-Laender", 0, 8),
        table_panel(5, "Firewall-Ereignisse", 12, 8, loki=True),
        geomap_panel(6, "Firewall-Weltkarte", 0, 16),
    ]
    dashboard = {
        "uid": "bocki-opnsense-firewall",
        "title": "OPNsense Firewall",
        "tags": ["bocki", "opnsense", "firewall"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "links": dashboard_switch_links(),
        "panels": panels,
    }
    return json.dumps(dashboard, indent=2) + "\n"


def flux_query(action: str) -> str:
    return f'''from(bucket: "firewall_metrics")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == "firewall_events" and r.action == "{action}")\n  |> sum()'''


def system_dashboard_json(bucket: str) -> str:
    panels: list[dict[str, Any]] = [
        system_timeseries(1, "CPU-Auslastung (%)", 0, 0, bucket, "cpu", "usage_active", 'r.cpu == "cpu-total"'),
        system_timeseries(2, "Speicherauslastung (%)", 12, 0, bucket, "mem", "used_percent"),
        system_timeseries(3, "Festplattenbelegung (%)", 0, 8, bucket, "disk", "used_percent", group_by="path"),
        system_timeseries(4, "Netzwerk-Durchsatz (Bytes/s)", 12, 8, bucket, "net", "bytes_recv", group_by="interface", derivative=True),
        system_timeseries(7, "CPU-Kerne (%)", 0, 24, bucket, "cpu", "usage_active", 'r.cpu != "cpu-total"', group_by="cpu"),
        system_stat(5, "Laufende Container", 0, 16, bucket, "docker", "n_containers_running"),
        system_table(6, "Container CPU (%)", 6, 16, bucket, "docker_container_cpu", "usage_percent", group_by="container_name"),
    ]
    dashboard = {
        "uid": "bocki-system-metrics",
        "title": "System-Metriken (Telegraf)",
        "tags": ["bocki", "telegraf", "system"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "links": dashboard_switch_links(),
        "panels": panels,
    }
    return json.dumps(dashboard, indent=2) + "\n"


def host_dashboard_json(bucket: str, uid: str, title: str, host_filter: str, include_docker: bool = False, include_temperature: bool = False) -> str:
    sections: list[dict[str, Any]] = [
        dashboard_section(1, "Uebersicht", [
            system_stat(101, "CPU-Auslastung", 0, 0, bucket, "cpu", "usage_active", 'r.cpu == "cpu-total"', host_filter),
            system_stat(102, "Speicherauslastung", 6, 0, bucket, "mem", "used_percent", host_filter=host_filter),
            system_stat(103, "Prozesse", 12, 0, bucket, "processes", "n_total", host_filter=host_filter),
        ]),
        dashboard_section(2, "System", [
            system_timeseries(201, "CPU-Auslastung (%)", 0, 0, bucket, "cpu", "usage_active", 'r.cpu == "cpu-total"', host_filter=host_filter),
            system_timeseries(202, "Speicherauslastung (%)", 12, 0, bucket, "mem", "used_percent", host_filter=host_filter),
            system_timeseries(203, "Festplattenbelegung (%)", 0, 8, bucket, "disk", "used_percent", group_by="path", host_filter=host_filter),
            system_timeseries(204, "Netzwerk Empfang", 12, 8, bucket, "net", "bytes_recv", group_by="interface", derivative=True, host_filter=host_filter),
            system_timeseries(206, "CPU-Temperatur", 0, 16, bucket, "temp", "temp", group_by="name", host_filter=host_filter),
            system_timeseries(207, "CPU-Kerne (%)", 12, 16, bucket, "cpu", "usage_active", 'r.cpu != "cpu-total"', group_by="cpu", host_filter=host_filter),
        ]),
    ]
    if include_temperature:
        sections[1]["panels"].append(system_timeseries(205, "CPU-Temperatur", 0, 16, bucket, "cpu_temperature", "value", host_filter=host_filter))
    if include_docker:
        sections.append(dashboard_section(3, "Docker", [
            system_timeseries(301, "Container CPU (%)", 0, 0, bucket, "docker_container_cpu", "usage_percent", group_by="container_name", host_filter=host_filter),
            system_table(302, "Container-Ressourcen", 12, 0, bucket, "docker_container_mem", "usage", group_by="container_name", host_filter=host_filter),
        ]))
        sections[1]["panels"].append(smart_temperature_panel(208, "Festplatten-Temperatur", 0, 24, bucket, host_filter))
    dashboard = {
        "uid": uid,
        "title": title,
        "tags": ["bocki", title.lower().replace(" ", "-"), "telegraf"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "links": dashboard_switch_links(),
        "panels": flatten_dashboard_sections(sections),
    }
    return json.dumps(dashboard, indent=2) + "\n"


def dashboard_switch_links() -> list[dict[str, Any]]:
    dashboards = [
        ("Bocki Gesamtuebersicht", "bocki-all-in-one"),
        ("Unraid", "bocki-unraid"),
        ("Raspberry", "bocki-raspberry"),
        ("OPNsense", "bocki-opnsense"),
    ]
    return [{
        "asDropdown": True,
        "icon": "external link",
        "includeVars": False,
        "keepTime": True,
        "tags": [],
        "title": "Bocki Dashboards",
        "type": "dashboards",
    }, *[
        {"title": title, "type": "dashboard", "uid": uid, "keepTime": True, "includeVars": False, "icon": "external link"}
        for title, uid in dashboards
    ]]


def unified_dashboard_json(bucket: str) -> str:
    panels = flatten_dashboard_sections([
        dashboard_section(1, "Uebersicht", [
            system_stat(101, "CPU-Auslastung", 0, 0, bucket, "cpu", "usage_active", 'r.cpu == "cpu-total"'),
            system_stat(102, "Speicherauslastung", 6, 0, bucket, "mem", "used_percent"),
            system_stat(103, "Laufende Container", 12, 0, bucket, "docker", "n_containers_running"),
            loki_stat(104, "Geblockte Firewall-Ereignisse", "action=\"block\"", "red"),
        ]),
        dashboard_section(2, "System", [
            system_timeseries(201, "CPU-Auslastung (%)", 0, 0, bucket, "cpu", "usage_active", 'r.cpu == "cpu-total"'),
            system_timeseries(202, "Speicherauslastung (%)", 12, 0, bucket, "mem", "used_percent"),
            system_timeseries(203, "Festplattenbelegung (%)", 0, 8, bucket, "disk", "used_percent", group_by="path"),
            system_timeseries(204, "CPU-Kerne (%)", 12, 8, bucket, "cpu", "usage_active", 'r.cpu != "cpu-total"', group_by="cpu"),
        ]),
        dashboard_section(3, "Docker", [
            system_timeseries(301, "Container CPU (%)", 0, 0, bucket, "docker_container_cpu", "usage_percent", group_by="container_name"),
            system_table(302, "Container-Ressourcen", 12, 0, bucket, "docker_container_mem", "usage", group_by="container_name"),
        ]),
        dashboard_section(4, "Netzwerk", [
            system_timeseries(401, "Empfangene Daten (Bytes/s)", 0, 0, bucket, "net", "bytes_recv", group_by="interface", derivative=True),
            system_timeseries(402, "Gesendete Daten (Bytes/s)", 12, 0, bucket, "net", "bytes_sent", group_by="interface", derivative=True),
        ]),
        dashboard_section(5, "OPNsense", [
            system_timeseries(501, "Firewall CPU (%)", 0, 0, bucket, "cpu", "usage_active", 'r.cpu == "cpu-total"'),
            system_timeseries(502, "Firewall RAM (%)", 12, 0, bucket, "mem", "used_percent"),
            system_timeseries(503, "Firewall Netzwerk", 0, 8, bucket, "net", "bytes_recv", group_by="interface", derivative=True),
        ]),
        dashboard_section(6, "Firewall", [
            loki_timeseries(601, "Pass / Block im Zeitverlauf", 0, 0),
            loki_logs(602, "Firewall-Ereignisse", 12, 0),
        ]),
    ])
    dashboard = {
        "uid": "bocki-all-in-one",
        "title": "Bocki Gesamtuebersicht",
        "tags": ["bocki", "overview", "system", "firewall"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "links": dashboard_switch_links(),
        "panels": panels,
    }
    return json.dumps(dashboard, indent=2) + "\n"


def dashboard_section(panel_id: int, title: str, panels: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": panel_id, "type": "row", "title": title, "collapsed": False, "panels": panels}


def flatten_dashboard_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    section_y = 0
    for section in sections:
        row = {key: value for key, value in section.items() if key != "panels"}
        row["gridPos"] = {"h": 1, "w": 24, "x": 0, "y": section_y}
        row["panels"] = []
        flattened.append(row)
        section_y += 1
        section_panels = section.get("panels", [])
        for panel in section_panels:
            panel = dict(panel)
            grid_pos = dict(panel.get("gridPos", {}))
            grid_pos["y"] = grid_pos.get("y", 0) + section_y
            panel["gridPos"] = grid_pos
            flattened.append(panel)
        section_y += max((panel.get("gridPos", {}).get("h", 0) for panel in section_panels), default=0)
    return flattened


def smart_temperature_panel(panel_id: int, title: str, x: int, y: int, bucket: str, host_filter: str) -> dict[str, Any]:
        query = f'''from(bucket: "{bucket}")
    |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
    |> filter(fn: (r) => r._measurement == "smart" and r._field =~ /temp/ and {host_filter})
    |> group(columns: ["disk"])'''
        return {"id": panel_id, "type": "timeseries", "title": title, "gridPos": {"h": 8, "w": 12, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "fieldConfig": {"defaults": {"unit": "celsius"}, "overrides": []}}


def loki_stat(panel_id: int, title: str, selector: str, color: str) -> dict[str, Any]:
    return {
        "id": panel_id, "type": "stat", "title": title, "gridPos": {"h": 6, "w": 6, "x": 18, "y": 0},
        "datasource": {"type": "loki", "uid": "Loki"},
        "targets": [{"refId": "A", "expr": f'sum(count_over_time({{{selector}}}[$__range]))', "queryType": "range"}],
        "fieldConfig": {"defaults": {"unit": "short", "color": {"mode": "fixed", "fixedColor": color}}, "overrides": []},
    }


def loki_timeseries(panel_id: int, title: str, x: int, y: int) -> dict[str, Any]:
    return {
        "id": panel_id, "type": "timeseries", "title": title, "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
        "datasource": {"type": "loki", "uid": "Loki"},
        "targets": [{"refId": "A", "expr": 'sum by (action) (count_over_time({service="filterlog"}[$__interval]))', "queryType": "range"}],
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
    }


def loki_logs(panel_id: int, title: str, x: int, y: int) -> dict[str, Any]:
    return {
        "id": panel_id, "type": "logs", "title": title, "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
        "datasource": {"type": "loki", "uid": "Loki"},
        "targets": [{"refId": "A", "expr": '{service="filterlog"}', "queryType": "range"}],
        "options": {"showTime": True, "showLabels": True, "wrapLines": False, "sortOrder": "Descending"},
    }


def _system_flux(bucket: str, measurement: str, field: str, filter_extra: str = "", group_by: str = "", derivative: bool = False, host_filter: str = "") -> str:
    source_field = field
    transform_active_cpu = measurement == "cpu" and field == "usage_active"
    if transform_active_cpu:
        source_field = "usage_idle"
    elif measurement == "processes" and field == "n_total":
        source_field = "total"
    filters = [f'r._measurement == "{measurement}"', f'r._field == "{source_field}"']
    if filter_extra:
        filters.append(filter_extra)
    if host_filter:
        filters.append(host_filter)
    extra_filter = " and " + " and ".join(filters[2:]) if len(filters) > 2 else ""
    query = f'from(bucket: "{bucket}")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "{field}"{extra_filter})'
    if transform_active_cpu:
        query = query.replace(f'r._field == "{field}"', f'r._field == "{source_field}"')
        query += '\n  |> map(fn: (r) => ({ r with _value: 100.0 - r._value }))'
    elif source_field != field:
        query = query.replace(f'r._field == "{field}"', f'r._field == "{source_field}"')
    if derivative:
        query += '\n  |> derivative(unit: 1s, nonNegative: true)'
    if group_by:
        query += f'\n  |> group(columns: ["{group_by}"])'
    return query


def system_timeseries(panel_id: int, title: str, x: int, y: int, bucket: str, measurement: str, field: str, filter_extra: str = "", group_by: str = "", derivative: bool = False, host_filter: str = "") -> dict[str, Any]:
    query = _system_flux(bucket, measurement, field, filter_extra, group_by, derivative, host_filter)
    return {"id": panel_id, "type": "timeseries", "title": title, "gridPos": {"h": 8, "w": 12, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []}}


def system_stat(panel_id: int, title: str, x: int, y: int, bucket: str, measurement: str, field: str, filter_extra: str = "", host_filter: str = "") -> dict[str, Any]:
    query = _system_flux(bucket, measurement, field, filter_extra, host_filter=host_filter)
    return {"id": panel_id, "type": "stat", "title": title, "gridPos": {"h": 6, "w": 6, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []}}


def system_table(panel_id: int, title: str, x: int, y: int, bucket: str, measurement: str, field: str, group_by: str = "", host_filter: str = "") -> dict[str, Any]:
    query = _system_flux(bucket, measurement, field, group_by=group_by, host_filter=host_filter)
    return {"id": panel_id, "type": "table", "title": title, "gridPos": {"h": 6, "w": 12, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "options": {"showHeader": True}}


def stat_panel(panel_id: int, title: str, action: str, x: int, y: int) -> dict[str, Any]:
    return {
        "id": panel_id, "type": "stat", "title": title, "gridPos": {"h": 4, "w": 6, "x": x, "y": y},
        "datasource": {"type": "influxdb", "uid": "InfluxDB"},
        "targets": [{"refId": "A", "query": flux_query(action)}],
        "fieldConfig": {"defaults": {"unit": "short", "color": {"mode": "fixed", "fixedColor": "red" if action == "block" else "green"}}, "overrides": []},
    }


def timeseries_panel(panel_id: int, title: str, x: int, y: int) -> dict[str, Any]:
    query = '''from(bucket: "firewall_metrics")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == "firewall_events" and r._field == "events")\n  |> aggregateWindow(every: v.windowPeriod, fn: sum, createEmpty: false)\n  |> group(columns: ["action"])'''
    return {"id": panel_id, "type": "timeseries", "title": title, "gridPos": {"h": 8, "w": 12, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "fieldConfig": {"defaults": {"unit": "short"}, "overrides": [{"matcher": {"id": "byName", "options": "block"}, "properties": [{"id": "color", "value": {"fixedColor": "red", "mode": "fixed"}}]}, {"matcher": {"id": "byName", "options": "pass"}, "properties": [{"id": "color", "value": {"fixedColor": "green", "mode": "fixed"}}]}]}}


def table_panel(panel_id: int, title: str, x: int, y: int, loki: bool = False) -> dict[str, Any]:
    if loki:
        datasource = {"type": "loki", "uid": "Loki"}
        target = {"refId": "A", "expr": "{service=\"filterlog\"}", "queryType": "range"}
    else:
        datasource = {"type": "influxdb", "uid": "InfluxDB"}
        target = {"refId": "A", "query": 'from(bucket: "firewall_metrics") |> range(start: v.timeRangeStart) |> filter(fn: (r) => r._measurement == "firewall_events") |> group(columns: ["country"]) |> sum()'}
    return {"id": panel_id, "type": "table", "title": title, "gridPos": {"h": 8, "w": 12, "x": x, "y": y}, "datasource": datasource, "targets": [target], "options": {"showHeader": True}}


def geomap_panel(panel_id: int, title: str, x: int, y: int) -> dict[str, Any]:
    query = 'from(bucket: "firewall_metrics") |> range(start: v.timeRangeStart) |> filter(fn: (r) => r._measurement == "firewall_events" and (r._field == "latitude" or r._field == "longitude"))'
    return {"id": panel_id, "type": "geomap", "title": title, "gridPos": {"h": 10, "w": 24, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "options": {"view": {"id": "fit"}, "basemap": {"config": {}, "name": "default", "type": "default"}, "layers": [{"config": {"style": {"color": {"field": "action", "fixed": "dark-red"}, "opacity": 0.7, "size": {"fixed": 5, "field": "events"}}}, "location": {"latitude": "latitude", "longitude": "longitude", "mode": "coords"}, "name": "Firewall", "tooltip": True, "type": "markers"}]}}
