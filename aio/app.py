"""Small dependency-free HTTP manager for the Unraid AIO container."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .docker_api import DockerApiError, DockerClient
from .orchestrator import StackOrchestrator
from .services import ALLOWED_ACTIONS, SERVICE_DEFINITIONS

MONITORING_NETWORK = "bocki-monitoring"

DEFAULT_CONFIG = {
    "configured": False,
    "organization": "home",
    "bucket": "homelab",
    "retention": "30d",
    "grafana_admin_user": "admin",
    "influx_admin_user": "admin",
    "host_data_dir": os.getenv("AIO_HOST_DATA_DIR", "/mnt/user/appdata/bocki-grafana-aio"),
    "grafana_port": int(os.getenv("AIO_GRAFANA_PORT", "3000")),
    "influxdb_port": int(os.getenv("AIO_INFLUXDB_PORT", "8086")),
    "loki_port": int(os.getenv("AIO_LOKI_PORT", "3100")),
    "alloy_port": int(os.getenv("AIO_ALLOY_PORT", "12345")),
    "proxy_host": os.getenv("AIO_PROXY_HOST", "172.17.0.1"),
    "syslog_port": int(os.getenv("AIO_SYSLOG_PORT", "5514")),
}


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(fallback)


class DockerUnavailable(RuntimeError):
    pass


class Manager:
    def __init__(self, data_dir: Path, docker: DockerClient | None = None) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = data_dir / "config.json"
        self.config = read_json(self.config_path, DEFAULT_CONFIG)
        self.docker = docker or DockerClient()
        self.docker_error: str | None = None
        self._connect_monitoring_network()

    def _connect_monitoring_network(self) -> None:
        if not Path(self.docker.socket_path).exists():
            self.docker_error = "Docker-Socket nicht gefunden: /var/run/docker.sock"
            return
        try:
            if not hasattr(self.docker, "connect_network"):
                return
            self.docker.ensure_network(MONITORING_NETWORK)
            self.docker.connect_network(MONITORING_NETWORK, "bocki-grafana-aio")
        except (OSError, DockerApiError, ValueError) as error:
            self.docker_error = str(error)

    def save_config(self, values: dict[str, Any]) -> None:
        config = dict(DEFAULT_CONFIG)
        config.update(self.config)
        config.update(values)
        config["configured"] = True
        config.setdefault("influx_admin_token", secrets.token_urlsafe(32))
        self.config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        self.config = config

    def install_stack(self) -> dict[str, Any]:
        if not self.config.get("configured"):
            raise ValueError("Bitte zuerst das Setup speichern")
        host_data_dir = Path(self.config.get("host_data_dir", os.getenv("AIO_HOST_DATA_DIR", "/mnt/user/appdata/bocki-grafana-aio")))
        try:
            created = StackOrchestrator(self.data_dir, host_data_dir, self.docker).install(self.config)
        except (DockerApiError, OSError, ValueError) as error:
            self.config["last_error"] = str(error)
            self.config_path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")
            raise
        self.config.pop("last_error", None)
        self.config_path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")
        return {"status": "installed", "created": created}

    def proxy_target(self, route: str) -> tuple[str, int, str] | None:
        proxy_host = self.config.get("proxy_host", "172.17.0.1")
        targets = {
            "grafana": (proxy_host, int(self.config.get("grafana_port", 3000))),
            "influxdb": (proxy_host, int(self.config.get("influxdb_port", 8086))),
            "loki": (proxy_host, 3100),
            "alloy": (proxy_host, 12345),
        }
        parts = route.strip("/").split("/", 1)
        target = targets.get(parts[0])
        if not target:
            return None
        return target[0], target[1], "/" + (parts[1] if len(parts) == 2 else "")

    def state(self) -> dict[str, Any]:
        containers = self._containers_by_service()
        return {
            "configured": bool(self.config.get("configured")),
            "config": {key: value for key, value in self.config.items() if "token" not in key and "password" not in key},
            "last_error": self.config.get("last_error"),
            "docker_error": self.docker_error,
            "services": {
                name: {"container": f"bocki-aio-{name}", "image": definition["image"], "status": containers.get(name, {}).get("status", "not-created")}
                for name, definition in SERVICE_DEFINITIONS.items()
            },
        }

    def _containers_by_service(self) -> dict[str, dict[str, Any]]:
        if not Path(self.docker.socket_path).exists():
            self.docker_error = "Docker-Socket nicht gefunden: /var/run/docker.sock"
            return {}
        try:
            containers = self.docker.containers()
        except (OSError, DockerApiError, ValueError) as error:
            self.docker_error = str(error)
            return {}
        self.docker_error = None
        result = {}
        for container in containers:
            names = container.get("Names", [])
            if not isinstance(names, list):
                continue
            name = next((str(item).lstrip("/") for item in names if str(item).lstrip("/").startswith("bocki-aio-")), "")
            service = name.removeprefix("bocki-aio-")
            if service in SERVICE_DEFINITIONS:
                result[service] = {"status": container.get("Status", "unknown"), "id": container.get("Id", "")}
        return result

    def service_action(self, service: str, action: str) -> dict[str, str]:
        if service not in SERVICE_DEFINITIONS:
            raise ValueError("Unbekannter Dienst")
        if action not in ALLOWED_ACTIONS:
            raise ValueError("Nicht erlaubte Aktion")
        if not Path(self.docker.socket_path).exists():
            raise DockerUnavailable("Docker-Socket nicht gefunden; Manager mit /var/run/docker.sock starten")
        container_name = f"bocki-aio-{service}"
        if action == "update":
            self.docker.pull(SERVICE_DEFINITIONS[service]["image"])
            return {"service": service, "action": action, "status": "image-pulled"}
        self.docker.action(container_name, action)
        return {"service": service, "action": action, "status": "requested"}


class Handler(BaseHTTPRequestHandler):
    manager: Manager

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/state":
            self._send(HTTPStatus.OK, self.manager.state())
            return
        if self.path in {"/", "/index.html"}:
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith(("/grafana", "/influxdb", "/loki", "/alloy")):
            self._proxy("GET")
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path.startswith(("/grafana", "/influxdb", "/loki", "/alloy")):
                self._proxy("POST")
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/setup":
                self._validate_setup(payload)
                self.manager.save_config(payload)
                self._send(HTTPStatus.OK, self.manager.state())
                return
            if self.path == "/api/install":
                self._send(HTTPStatus.OK, self.manager.install_stack())
                return
            prefix = "/api/services/"
            if self.path.startswith(prefix):
                service, action = self.path[len(prefix):].split("/", 1)
                result = self.manager.service_action(service, action)
                self._send(HTTPStatus.OK, result)
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})
        except (ValueError, json.JSONDecodeError, DockerUnavailable, DockerApiError, OSError) as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy("DELETE")

    def _proxy(self, method: str) -> None:
        route, _, query = self.path.partition("?")
        target = self.manager.proxy_target(route)
        if not target:
            self._send(HTTPStatus.NOT_FOUND, {"error": "Unbekannter Dienst"})
            return
        hostname, port, path = target
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))) if method in {"POST", "PUT", "DELETE"} else None
        connection = http.client.HTTPConnection(hostname, port, timeout=10)
        try:
            connection.request(method, path + ("?" + query if query else ""), body=body, headers={"Content-Type": self.headers.get("Content-Type", "application/octet-stream")})
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "content-length", "transfer-encoding"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (OSError, http.client.HTTPException) as error:
            self._send(HTTPStatus.BAD_GATEWAY, {"error": f"Dienst nicht erreichbar: {error}"})
        finally:
            connection.close()

    @staticmethod
    def _validate_setup(payload: dict[str, Any]) -> None:
        required = ("grafana_admin_password", "influx_admin_password")
        if any(not str(payload.get(key, "")).strip() for key in required):
            raise ValueError("Grafana- und InfluxDB-Passwort sind erforderlich")
        for key in ("organization", "bucket", "retention", "grafana_admin_user"):
            if payload.get(key) and len(str(payload[key])) > 100:
                raise ValueError(f"Wert fuer {key} ist zu lang")

    def log_message(self, format: str, *args: object) -> None:
        return


INDEX_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bocki Grafana AIO</title><style>
:root{font-family:ui-sans-serif,system-ui,sans-serif;color:#17212b;background:#eef1ed}body{max-width:980px;margin:0 auto;padding:28px}header{border-bottom:1px solid #c9d1c8;margin-bottom:22px}h1{font-size:2rem;margin:0 0 8px;color:#174a4a}section{background:#fff;border:1px solid #d5ddd4;border-radius:8px;padding:20px;margin:14px 0;box-shadow:0 3px 12px #173b3b12}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}label{display:grid;gap:6px;font-size:.9rem}input{padding:10px;border:1px solid #bdc8be;border-radius:5px;font:inherit}button{background:#d85b35;color:#fff;border:0;border-radius:5px;padding:10px 14px;font:inherit;cursor:pointer}button:hover{background:#b94727}.service{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #e2e7e1;padding:12px 0}.muted{color:#607067}#message{min-height:1.5em}</style></head>
<body><header><h1>Bocki Grafana AIO</h1><p class="muted">Einrichtung und Status der Monitoring-Dienste</p><p class="muted">Manager-Updates werden in Unraid über <strong>Force Update</strong> am Container eingespielt.</p></header>
<section><h2>Ersteinrichtung</h2><form id="setup"><div class="grid"><label>Grafana Benutzer<input name="grafana_admin_user" value="admin"></label><label>Grafana Passwort<input name="grafana_admin_password" type="password" required></label><label>InfluxDB Passwort<input name="influx_admin_password" type="password" required></label><label>Organisation<input name="organization" value="home"></label><label>Bucket<input name="bucket" value="homelab"></label><label>Retention<input name="retention" value="30d"></label></div><p><button>Setup speichern</button></p></form><p id="message" class="muted"></p></section>
<section><h2>Dienste</h2><p class="muted">Weboberflaechen und APIs sind ueber diesen Manager erreichbar:</p><div class="grid"><a href="/grafana/" target="_blank" rel="noreferrer">Grafana</a><a href="/influxdb/" target="_blank" rel="noreferrer">InfluxDB</a><a href="/loki/ready" target="_blank" rel="noreferrer">Loki API</a><a href="/alloy/-/ready" target="_blank" rel="noreferrer">Alloy Status</a></div><div id="services"></div></section>
<script>
async function state(){const response=await fetch('/api/state');const data=await response.json();document.getElementById('services').innerHTML=Object.entries(data.services).map(([name,item])=>`<div class="service"><span><strong>${name}</strong><br><small class="muted">${item.container} &middot; ${item.image}</small></span><span>${item.status}</span></div>`).join('');if(data.docker_error)document.getElementById('message').textContent='Docker-Fehler: '+data.docker_error;else if(data.last_error)document.getElementById('message').textContent='Letzter Installationsfehler: '+data.last_error}
document.getElementById('setup').addEventListener('submit',async event=>{event.preventDefault();const payload=Object.fromEntries(new FormData(event.target));const response=await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(data.error){document.getElementById('message').textContent=data.error;return}document.getElementById('message').textContent='Konfiguration gespeichert, Dienste werden erstellt...';const install=await fetch('/api/install',{method:'POST'});const result=await install.json();document.getElementById('message').textContent=result.error||`${result.created.length} Dienste erstellt.`;state()});state();
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8800")))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("AIO_DATA_DIR", "/data")))
    args = parser.parse_args()
    manager = Manager(args.data_dir)
    Handler.manager = manager
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"Bocki Grafana AIO listening on {args.bind}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
