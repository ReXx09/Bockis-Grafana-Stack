"""Build persistent configs and Docker container specifications for the stack."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dashboard import dashboard_json
from .services import SERVICE_DEFINITIONS

NETWORK_NAME = "bocki-monitoring"


class StackOrchestrator:
    def __init__(self, data_dir: Path, host_data_dir: Path, docker: Any) -> None:
        self.data_dir = data_dir
        self.host_data_dir = host_data_dir
        self.docker = docker
        self.generated_dir = data_dir / "generated"
        self.host_generated_dir = host_data_dir / "generated"

    def provision_files(self, config: dict[str, Any]) -> None:
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.host_generated_dir.mkdir(parents=True, exist_ok=True)
        for name in ("influxdb", "influxdb-config", "grafana", "loki"):
            directory = self.host_data_dir / name
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o777)
        custom_telegraf = self.host_data_dir / "telegraf.custom.conf"
        telegraf_content = custom_telegraf.read_text(encoding="utf-8") if custom_telegraf.exists() else telegraf_config(config)
        files = {
            "loki-config.yml": LOKI_CONFIG,
            "alloy-config.alloy": ALLOY_CONFIG,
            "telegraf.conf": telegraf_content,
            "grafana-datasource.yml": grafana_datasource(config),
            "grafana-dashboards.yml": GRAFANA_DASHBOARDS,
            "opnsense-firewall-v1.json": dashboard_json(),
        }
        for name, content in files.items():
            (self.generated_dir / name).write_text(content, encoding="utf-8")
            (self.host_generated_dir / name).write_text(content, encoding="utf-8")

    def install(self, config: dict[str, Any]) -> list[str]:
        self.provision_files(config)
        self.docker.ensure_network(NETWORK_NAME)
        manager_name = config.get("manager_container_name", "bocki-grafana-aio")
        try:
            self.docker.connect_network(NETWORK_NAME, manager_name)
        except Exception:
            pass
        created = []
        for service, definition in SERVICE_DEFINITIONS.items():
            name = f"bocki-aio-{service}"
            if self.docker.container_exists(name):
                continue
            self.docker.pull(definition["image"])
            self.docker.create_container(name, self.container_spec(service, config))
            self.docker.start(name)
            created.append(service)
        return created

    def reinstall(self, config: dict[str, Any]) -> list[str]:
        self.provision_files(config)
        self.docker.ensure_network(NETWORK_NAME)
        manager_name = config.get("manager_container_name", "bocki-grafana-aio")
        try:
            self.docker.connect_network(NETWORK_NAME, manager_name)
        except Exception:
            pass
        recreated = []
        for service, definition in SERVICE_DEFINITIONS.items():
            name = f"bocki-aio-{service}"
            if self.docker.container_exists(name):
                self.docker.remove(name)
            self.docker.pull(definition["image"])
            self.docker.create_container(name, self.container_spec(service, config))
            self.docker.start(name)
            recreated.append(service)
        return recreated

    def container_spec(self, service: str, config: dict[str, Any]) -> dict[str, Any]:
        image = SERVICE_DEFINITIONS[service]["image"]
        host = self.host_data_dir
        binds = []
        environment = ["TZ=Europe/Berlin"]
        ports: dict[str, list[dict[str, str]]] = {}
        exposed: dict[str, dict[str, object]] = {}

        if service == "influxdb":
            binds += [f"{host / 'influxdb'}:/var/lib/influxdb2", f"{host / 'influxdb-config'}:/etc/influxdb2"]
            environment += [
                "DOCKER_INFLUXDB_INIT_MODE=setup",
                f"DOCKER_INFLUXDB_INIT_USERNAME={config['influx_admin_user']}",
                f"DOCKER_INFLUXDB_INIT_PASSWORD={config['influx_admin_password']}",
                f"DOCKER_INFLUXDB_INIT_ADMIN_TOKEN={config['influx_admin_token']}",
                f"DOCKER_INFLUXDB_INIT_ORG={config['organization']}",
                f"DOCKER_INFLUXDB_INIT_BUCKET={config['bucket']}",
                f"DOCKER_INFLUXDB_INIT_RETENTION={config['retention']}",
            ]
            add_port(ports, exposed, 8086, config.get("influxdb_port", 8086), "tcp")
        elif service == "grafana":
            binds += [
                f"{host / 'grafana'}:/var/lib/grafana",
                f"{self.host_generated_dir / 'grafana-datasource.yml'}:/etc/grafana/provisioning/datasources/datasource.yml:ro",
                f"{self.host_generated_dir / 'grafana-dashboards.yml'}:/etc/grafana/provisioning/dashboards/dashboards.yml:ro",
                f"{self.host_generated_dir / 'opnsense-firewall-v1.json'}:/var/lib/grafana/dashboards/opnsense-firewall-v1.json:ro",
            ]
            environment += [
                f"GF_SECURITY_ADMIN_USER={config['grafana_admin_user']}",
                f"GF_SECURITY_ADMIN_PASSWORD={config['grafana_admin_password']}",
                "GF_USERS_ALLOW_SIGN_UP=false",
                "GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s/grafana/",
                "GF_SERVER_SERVE_FROM_SUB_PATH=true",
            ]
            add_port(ports, exposed, 3000, config.get("grafana_port", 3000), "tcp")
        elif service == "telegraf":
            binds += [f"{self.host_generated_dir / 'telegraf.conf'}:/etc/telegraf/telegraf.conf:ro", "/var/run/docker.sock:/var/run/docker.sock:ro"]
            environment += [f"INFLUX_TOKEN={config['influx_admin_token']}", f"INFLUX_ORG={config['organization']}", f"INFLUX_BUCKET={config['bucket']}"]
        elif service == "loki":
            binds += [f"{host / 'loki'}:/loki", f"{self.host_generated_dir / 'loki-config.yml'}:/etc/loki/config.yml:ro"]
            add_port(ports, exposed, 3100, config.get("loki_port", 3100), "tcp")
        elif service == "alloy":
            binds += [f"{self.host_generated_dir / 'alloy-config.alloy'}:/etc/alloy/config.alloy:ro"]
            add_port(ports, exposed, 5514, config.get("syslog_port", 5514), "udp")
            add_port(ports, exposed, 12345, config.get("alloy_port", 12345), "tcp")

        spec = {
            "Image": image,
            "Env": environment,
            "HostConfig": {"Binds": binds, "RestartPolicy": {"Name": "unless-stopped"}, "PortBindings": ports, "NetworkMode": NETWORK_NAME},
            "NetworkingConfig": {"EndpointsConfig": {NETWORK_NAME: {"Aliases": [service]}}},
        }
        if service == "telegraf":
            spec["User"] = "0"
        if service == "grafana":
            spec["User"] = "0"
        if service == "loki":
            spec["User"] = "0"
        if service == "influxdb":
            spec["User"] = "0"
        healthcheck = SERVICE_DEFINITIONS[service].get("healthcheck")
        if healthcheck:
            spec["Healthcheck"] = {"Test": healthcheck, "Interval": 30_000_000_000, "Timeout": 10_000_000_000, "Retries": 5, "StartPeriod": 20_000_000_000}
        if exposed:
            spec["ExposedPorts"] = exposed
        if service == "loki":
            spec["Cmd"] = ["-config.file=/etc/loki/config.yml"]
        if service == "alloy":
            spec["Cmd"] = ["run", "--server.http.listen-addr=0.0.0.0:12345", "/etc/alloy/config.alloy"]
        return spec


def add_port(bindings: dict[str, list[dict[str, str]]], exposed: dict[str, dict[str, object]], internal: int, external: int, protocol: str) -> None:
    key = f"{internal}/{protocol}"
    bindings[key] = [{"HostPort": str(external)}]
    exposed[key] = {}


def telegraf_config(config: dict[str, Any]) -> str:
    return f'''[agent]\n  interval = "10s"\n  round_interval = true\n  hostname = "bocki-aio"\n\n[[outputs.influxdb_v2]]\n  urls = ["http://influxdb:8086"]\n  token = "{config["influx_admin_token"]}"\n  organization = "{config["organization"]}"\n  bucket = "{config["bucket"]}"\n\n[[inputs.cpu]]\n  percpu = true\n  totalcpu = true\n\n[[inputs.mem]]\n[[inputs.net]]\n[[inputs.disk]]\n  ignore_fs = ["tmpfs", "devtmpfs", "devfs", "overlay"]\n[[inputs.docker]]\n  endpoint = "unix:///var/run/docker.sock"\n'''


def grafana_datasource(config: dict[str, Any]) -> str:
    payload = {
        "apiVersion": 1,
        "datasources": [
            {"uid": "InfluxDB", "name": "InfluxDB", "type": "influxdb", "access": "proxy", "url": "http://influxdb:8086", "database": config["bucket"], "jsonData": {"version": "Flux", "organization": config["organization"], "defaultBucket": config["bucket"], "tlsSkipVerify": True}, "secureJsonData": {"token": config["influx_admin_token"]}, "isDefault": True},
            {"uid": "Loki", "name": "Loki", "type": "loki", "access": "proxy", "url": "http://loki:3100"},
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


GRAFANA_DASHBOARDS = """apiVersion: 1\nproviders:\n  - name: Bocki\n    type: file\n    updateIntervalSeconds: 30\n    options:\n      path: /var/lib/grafana/dashboards\n"""

LOKI_CONFIG = """auth_enabled: false\nserver:\n  http_listen_port: 3100\ncommon:\n  path_prefix: /loki\n  storage:\n    filesystem:\n      chunks_directory: /loki/chunks\n      rules_directory: /loki/rules\n  replication_factor: 1\n  ring:\n    kvstore:\n      store: inmemory\nschema_config:\n  configs:\n    - from: 2024-01-01\n      store: tsdb\n      object_store: filesystem\n      schema: v13\n      index:\n        prefix: index_\n        period: 24h\nlimits_config:\n  retention_period: 168h\ncompactor:\n  working_directory: /loki/compactor\n  retention_enabled: true\n  delete_request_store: filesystem\n"""

ALLOY_CONFIG = """logging {\n  level = "info"\n}\n\nloki.source.syslog "opnsense" {\n  listener {\n    address = "0.0.0.0:5514"\n    protocol = "udp"\n    syslog_format = "rfc3164"\n    labels = { source = "opnsense", service = "filterlog" }\n  }\n  forward_to = [loki.process.filterlog.receiver]\n}\n\nloki.process "filterlog" {\n  stage.regex {\n    expression = "filterlog: [^,]*,[^,]*,[^,]*,[^,]*,(?P<interface>[^,]*),[^,]*,(?P<action>[^,]*),(?P<direction>[^,]*),[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(?P<protocol>[^,]*),[^,]*,(?P<source_ip>[^,]*),(?P<destination_ip>[^,]*),(?P<source_port>[^,]*),(?P<destination_port>[^,]*)"\n  }\n  stage.labels {\n    values = { action = "action", direction = "direction", interface = "interface", protocol = "protocol" }\n  }\n  stage.structured_metadata {\n    values = { source_ip = "source_ip", destination_ip = "destination_ip", source_port = "source_port", destination_port = "destination_port" }\n  }\n  forward_to = [loki.write.local.receiver]\n}\n\nloki.write "local" {\n  endpoint {\n    url = "http://loki:3100/loki/api/v1/push"\n  }\n}\n"""
