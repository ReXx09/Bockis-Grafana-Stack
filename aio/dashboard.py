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
        "panels": panels,
    }
    return json.dumps(dashboard, indent=2) + "\n"


def _system_flux(bucket: str, measurement: str, field: str, filter_extra: str = "", group_by: str = "", derivative: bool = False) -> str:
    extra_filter = f" and {filter_extra}" if filter_extra else ""
    query = f'from(bucket: "{bucket}")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n  |> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "{field}"{extra_filter})'
    if derivative:
        query += '\n  |> derivative(unit: 1s, nonNegative: true)'
    if group_by:
        query += f'\n  |> group(columns: ["{group_by}"])'
    return query


def system_timeseries(panel_id: int, title: str, x: int, y: int, bucket: str, measurement: str, field: str, filter_extra: str = "", group_by: str = "", derivative: bool = False) -> dict[str, Any]:
    query = _system_flux(bucket, measurement, field, filter_extra, group_by, derivative)
    return {"id": panel_id, "type": "timeseries", "title": title, "gridPos": {"h": 8, "w": 12, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []}}


def system_stat(panel_id: int, title: str, x: int, y: int, bucket: str, measurement: str, field: str) -> dict[str, Any]:
    query = _system_flux(bucket, measurement, field)
    return {"id": panel_id, "type": "stat", "title": title, "gridPos": {"h": 6, "w": 6, "x": x, "y": y}, "datasource": {"type": "influxdb", "uid": "InfluxDB"}, "targets": [{"refId": "A", "query": query}], "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []}}


def system_table(panel_id: int, title: str, x: int, y: int, bucket: str, measurement: str, field: str, group_by: str = "") -> dict[str, Any]:
    query = _system_flux(bucket, measurement, field, group_by=group_by)
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
