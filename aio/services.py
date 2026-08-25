"""Versioned service definitions for the Bocki Grafana AIO manager."""

SERVICE_DEFINITIONS = {
    "influxdb": {
        "image": "influxdb:2.7",
        "internal_port": 8086,
        "health_url": "http://influxdb:8086/health",
        "healthcheck": ["CMD", "influx", "ping", "--host", "http://localhost:8086"],
    },
    "grafana": {
        "image": "grafana/grafana:11.5.2",
        "internal_port": 3000,
        "health_url": "http://grafana:3000/api/health",
        "healthcheck": ["CMD-SHELL", "wget -q -O - http://localhost:3000/api/health || exit 1"],
    },
    "telegraf": {
        "image": "telegraf:1.34",
        "internal_port": None,
        "health_url": None,
    },
    "loki": {
        "image": "grafana/loki:3.4.2",
        "internal_port": 3100,
        "health_url": "http://loki:3100/ready",
        "healthcheck": ["CMD-SHELL", "wget -q -O - http://localhost:3100/ready || exit 1"],
    },
    "alloy": {
        "image": "grafana/alloy:v1.7.5",
        "internal_port": 12345,
        "health_url": "http://alloy:12345/-/ready",
        "healthcheck": ["CMD-SHELL", "wget -q -O - http://localhost:12345/-/ready || exit 1"],
    },
}

ALLOWED_ACTIONS = {"start", "stop", "restart", "update"}
