"""Small dependency-free HTTP manager for the Unraid AIO container."""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import secrets
import shutil
import tomllib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .docker_api import DockerApiError, DockerClient
from .orchestrator import StackOrchestrator, telegraf_config
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
        self.admin_user = os.getenv("AIO_ADMIN_USER", "admin")
        self.admin_password = self._load_admin_password()
        self._connect_monitoring_network()

    def _load_admin_password(self) -> str:
        env_password = os.getenv("AIO_ADMIN_PASSWORD", "").strip()
        if env_password:
            return env_password
        secret_path = self.data_dir / "admin_password.txt"
        if secret_path.exists():
            return secret_path.read_text(encoding="utf-8").strip()
        password = secrets.token_urlsafe(18)
        secret_path.write_text(password, encoding="utf-8")
        return password

    def _connect_monitoring_network(self) -> None:
        if not Path(self.docker.socket_path).exists():
            self.docker_error = "Docker-Socket nicht gefunden: /var/run/docker.sock"
            return
        try:
            if not hasattr(self.docker, "connect_network"):
                return
            self.docker.ensure_network(MONITORING_NETWORK)
            self.docker.connect_network(MONITORING_NETWORK, "bocki-grafana-aio")
            for service in SERVICE_DEFINITIONS:
                container_name = f"bocki-aio-{service}"
                try:
                    self.docker.connect_network(MONITORING_NETWORK, container_name)
                except DockerApiError as error:
                    if "no such container" not in str(error).lower():
                        raise
        except (OSError, DockerApiError, ValueError) as error:
            self.docker_error = str(error)

    def save_config(self, values: dict[str, Any]) -> None:
        config = dict(DEFAULT_CONFIG)
        config.update(self.config)
        secret_fields = {"grafana_admin_password", "influx_admin_password"}
        for key, value in values.items():
            if key in secret_fields and not str(value).strip():
                continue
            config[key] = value
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

    def reinstall_stack(self) -> dict[str, Any]:
        if not self.config.get("configured"):
            raise ValueError("Bitte zuerst das Setup speichern")
        backup_dir = self.data_dir / "backups" / secrets.token_hex(6)
        backup_dir.mkdir(parents=True, exist_ok=False)
        for path in (self.config_path, self.data_dir / "admin_password.txt"):
            if path.exists():
                shutil.copy2(path, backup_dir / path.name)
        generated_dir = self.data_dir / "generated"
        if generated_dir.exists():
            shutil.copytree(generated_dir, backup_dir / "generated")
        host_data_dir = Path(self.config.get("host_data_dir", os.getenv("AIO_HOST_DATA_DIR", "/mnt/user/appdata/bocki-grafana-aio")))
        try:
            recreated = StackOrchestrator(self.data_dir, host_data_dir, self.docker).reinstall(self.config)
        except (DockerApiError, OSError, ValueError) as error:
            self.config["last_error"] = str(error)
            self.config_path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")
            raise
        self.config.pop("last_error", None)
        self.config_path.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")
        return {"status": "reinstalled", "recreated": recreated, "backup": str(backup_dir)}

    def proxy_target(self, route: str) -> tuple[str, int, str] | None:
        ports = {
            "grafana": 3000,
            "influxdb": 8086,
            "loki": 3100,
            "alloy": 12345,
        }
        parts = route.strip("/").split("/", 1)
        service = parts[0]
        if service not in ports:
            return None
        container_name = f"bocki-aio-{service}"
        address = container_name
        try:
            if hasattr(self.docker, "connect_network"):
                self.docker.connect_network(MONITORING_NETWORK, "bocki-grafana-aio")
                self.docker.connect_network(MONITORING_NETWORK, container_name)
            details = self.docker.inspect(container_name)
            networks = details.get("NetworkSettings", {}).get("Networks", {})
            network = networks.get(MONITORING_NETWORK, {})
            inspected_address = network.get("IPAddress", "")
            if not inspected_address:
                inspected_address = next((item.get("IPAddress", "") for item in networks.values() if item.get("IPAddress")), "")
            if inspected_address:
                address = inspected_address
        except (OSError, DockerApiError, ValueError, AttributeError):
            pass
        return address, ports[service], "/" + (parts[1] if len(parts) == 2 else "")

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
        for service in SERVICE_DEFINITIONS:
            if service in result:
                continue
            try:
                details = self.docker.inspect(f"bocki-aio-{service}")
                state = details.get("State", {})
                if isinstance(state, dict) and state.get("Status"):
                    result[service] = {"status": state["Status"], "id": details.get("Id", "")}
            except (OSError, DockerApiError, ValueError, AttributeError):
                continue
        return result

    def service_action(self, service: str, action: str) -> dict[str, Any]:
        if service not in SERVICE_DEFINITIONS:
            raise ValueError("Unbekannter Dienst")
        if action not in ALLOWED_ACTIONS:
            raise ValueError("Nicht erlaubte Aktion")
        if not Path(self.docker.socket_path).exists():
            raise DockerUnavailable("Docker-Socket nicht gefunden; Manager mit /var/run/docker.sock starten")
        container_name = f"bocki-aio-{service}"
        if action == "update":
            image = SERVICE_DEFINITIONS[service]["image"]
            old_image_id = ""
            try:
                old_image_id = str(self.docker.inspect(container_name).get("Image", ""))
            except (OSError, DockerApiError, ValueError):
                pass
            self.docker.pull(image)
            new_image_id = self.docker.image_id(image)
            update_available = bool(old_image_id) and bool(new_image_id) and old_image_id != new_image_id
            return {"service": service, "action": action, "status": "image-pulled", "update_available": update_available}
        self.docker.action(container_name, action)
        return {"service": service, "action": action, "status": "requested"}

    def service_logs(self, service: str, tail: int = 200) -> str:
        if service not in SERVICE_DEFINITIONS:
            raise ValueError("Unbekannter Dienst")
        if not Path(self.docker.socket_path).exists():
            raise DockerUnavailable("Docker-Socket nicht gefunden; Manager mit /var/run/docker.sock starten")
        return self.docker.logs(f"bocki-aio-{service}", tail=tail)

    def telegraf_config(self) -> str:
        path = Path(self.config.get("host_data_dir", DEFAULT_CONFIG["host_data_dir"])) / "telegraf.custom.conf"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return telegraf_config(self.config)

    def save_telegraf_config(self, content: str) -> str:
        if not content.strip():
            raise ValueError("Telegraf-Konfiguration darf nicht leer sein")
        if len(content.encode("utf-8")) > 512_000:
            raise ValueError("Telegraf-Konfiguration ist zu gross")
        try:
            tomllib.loads(content)
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"Ungueltige Telegraf-TOML: {error}") from error
        host_data_dir = Path(self.config.get("host_data_dir", DEFAULT_CONFIG["host_data_dir"]))
        host_data_dir.mkdir(parents=True, exist_ok=True)
        custom_path = host_data_dir / "telegraf.custom.conf"
        backup_dir = self.data_dir / "backups" / "telegraf"
        backup_dir.mkdir(parents=True, exist_ok=True)
        if custom_path.exists():
            backup_path = backup_dir / f"telegraf-{secrets.token_hex(6)}.conf"
            shutil.copy2(custom_path, backup_path)
        temporary_path = custom_path.with_name(f".{custom_path.name}.{secrets.token_hex(6)}.tmp")
        try:
            temporary_path.write_text(content, encoding="utf-8")
            os.replace(temporary_path, custom_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        StackOrchestrator(self.data_dir, host_data_dir, self.docker).provision_files(self.config)
        if self.docker.container_exists("bocki-aio-telegraf"):
            self.docker.action("bocki-aio-telegraf", "restart")
        return str(custom_path)


class Handler(BaseHTTPRequestHandler):
    manager: Manager

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authenticated(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return secrets.compare_digest(user, self.manager.admin_user) and secrets.compare_digest(password, self.manager.admin_password)

    def _require_auth(self) -> bool:
        if self._authenticated():
            return True
        self._send_unauthorized()
        return False

    def _send_unauthorized(self) -> None:
        body = json.dumps({"error": "Nicht autorisiert"}).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Bocki Grafana AIO"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not self._require_auth():
            return
        if self.path == "/api/state":
            self._send(HTTPStatus.OK, self.manager.state())
            return
        if self.path == "/api/config/telegraf":
            self._send(HTTPStatus.OK, {"config": self.manager.telegraf_config()})
            return
        if self.path in {"/", "/index.html"}:
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        prefix = "/api/services/"
        if self.path.startswith(prefix) and self.path.endswith("/logs"):
            service = self.path[len(prefix):-len("/logs")]
            try:
                logs = self.manager.service_logs(service)
                self._send(HTTPStatus.OK, {"service": service, "logs": logs})
            except (ValueError, DockerUnavailable, DockerApiError, OSError) as error:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if self.path.startswith(("/grafana", "/influxdb", "/loki", "/alloy")):
            self._proxy("GET")
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "Nicht gefunden"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_auth():
            return
        try:
            if self.path.startswith(("/grafana", "/influxdb", "/loki", "/alloy")):
                self._proxy("POST")
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/setup":
                self._validate_setup(payload, bool(self.manager.config.get("configured")))
                self.manager.save_config(payload)
                self._send(HTTPStatus.OK, self.manager.state())
                return
            if self.path == "/api/config/telegraf":
                path = self.manager.save_telegraf_config(str(payload.get("config", "")))
                self._send(HTTPStatus.OK, {"status": "saved", "path": path})
                return
            if self.path == "/api/install":
                self._send(HTTPStatus.OK, self.manager.install_stack())
                return
            if self.path == "/api/reinstall":
                if payload.get("confirm") is not True:
                    raise ValueError("Reinstall muss bestaetigt werden")
                self._send(HTTPStatus.OK, self.manager.reinstall_stack())
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
        if not self._require_auth():
            return
        self._proxy("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._require_auth():
            return
        self._proxy("DELETE")

    def _proxy(self, method: str) -> None:
        route, _, query = self.path.partition("?")
        target = self.manager.proxy_target(route)
        if not target:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Dienst ist nicht im Netzwerk bocki-monitoring erreichbar"})
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
    def _validate_setup(payload: dict[str, Any], configured: bool = False) -> None:
        required = ("grafana_admin_password", "influx_admin_password")
        if not configured and any(not str(payload.get(key, "")).strip() for key in required):
            raise ValueError("Grafana- und InfluxDB-Passwort sind erforderlich")
        for key in required:
            value = str(payload.get(key, ""))
            if value and not 8 <= len(value) <= 72:
                raise ValueError(f"{key} muss zwischen 8 und 72 Zeichen lang sein")
        for key in ("organization", "bucket", "retention", "grafana_admin_user"):
            if payload.get(key) and len(str(payload[key])) > 100:
                raise ValueError(f"Wert fuer {key} ist zu lang")

    def log_message(self, format: str, *args: object) -> None:
        return


INDEX_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bocki Grafana AIO</title><style>
:root{font-family:ui-sans-serif,system-ui,sans-serif;color:#17212b;background:#eef1ed}body{max-width:980px;margin:0 auto;padding:28px}header{border-bottom:1px solid #c9d1c8;margin-bottom:22px}h1{font-size:2rem;margin:0 0 8px;color:#174a4a}section{background:#fff;border:1px solid #d5ddd4;border-radius:8px;padding:20px;margin:14px 0;box-shadow:0 3px 12px #173b3b12}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}label{display:grid;gap:6px;font-size:.9rem}input{padding:10px;border:1px solid #bdc8be;border-radius:5px;font:inherit}button{background:#d85b35;color:#fff;border:0;border-radius:5px;padding:10px 14px;font:inherit;cursor:pointer}button:hover{background:#b94727}button:disabled{opacity:.5;cursor:progress}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px 8px;border-top:1px solid #e2e7e1}th{color:#607067;font-weight:600;font-size:.85rem}.muted{color:#607067}#message{min-height:1.5em}.badge{padding:3px 10px;border-radius:12px;font-size:.8rem;background:#e2e7e1;white-space:nowrap}.status-ok{background:#dff3e0;color:#1f7a35}.status-warn{background:#fdf1d8;color:#9a6b06}.status-bad{background:#fbdede;color:#a3272c}.actions button{margin:2px;padding:6px 10px;font-size:.78rem}#live-log{background:#101a1a;color:#d7e6df;border-radius:6px;padding:10px;max-height:180px;overflow:auto;font-size:.78rem;white-space:pre-wrap}dialog#logs-modal{width:min(720px,90vw);border:1px solid #d5ddd4;border-radius:8px;padding:16px}#logs-content{white-space:pre-wrap;max-height:60vh;overflow:auto;background:#101a1a;color:#d7e6df;padding:12px;border-radius:6px;font-size:.78rem}</style></head>
<body><header><h1>Bocki Grafana AIO</h1><p class="muted">Einrichtung und Status der Monitoring-Dienste</p><p class="muted">Manager-Updates werden in Unraid über <strong>Force Update</strong> am Container eingespielt.</p></header>
<section><h2>Ersteinrichtung</h2><form id="setup"><div class="grid"><label>Grafana Benutzer<input name="grafana_admin_user" value="admin"></label><label>Grafana Passwort<input name="grafana_admin_password" type="password" placeholder="Leer lassen = unveraendert"></label><label>InfluxDB Passwort<input name="influx_admin_password" type="password" placeholder="Leer lassen = unveraendert"></label><label>Organisation<input name="organization" value="home"></label><label>Bucket<input name="bucket" value="homelab"></label><label>Retention<input name="retention" value="30d"></label></div><p><button>Setup speichern</button></p></form><p id="message" class="muted"></p><h3>Live-Log</h3><pre id="live-log">Noch keine Aktionen.</pre><p><button id="clear-log" type="button">Log leeren</button></p></section>
<section><h2>Dienste</h2><p class="muted">Weboberflaechen und APIs sind ueber diesen Manager erreichbar:</p><p><button id="reinstall" type="button">Stack neu erstellen</button></p><table><thead><tr><th>Dienst</th><th>WebUI</th><th>Container</th><th>Status</th><th>Aktionen</th></tr></thead><tbody id="services"></tbody></table></section>
<section><h2>Telegraf-Konfiguration</h2><p class="muted">Die aktive Konfiguration wird vor dem Speichern gesichert und nach dem Speichern neu geladen.</p><textarea id="telegraf-config" rows="20" spellcheck="false" style="width:100%;box-sizing:border-box;font:12px monospace;padding:10px;border:1px solid #bdc8be;border-radius:5px"></textarea><p><button id="telegraf-load" type="button">Laden</button> <button id="telegraf-save" type="button">Speichern und neu starten</button></p></section>
<dialog id="logs-modal"><h3 id="logs-title"></h3><pre id="logs-content"></pre><p><button id="logs-close" type="button">Schliessen</button></p></dialog>
<script>
const SERVICE_LINKS={grafana:'/grafana/'};
const DIRECT_PORTS={influxdb:'influxdb_port',loki:'loki_port',alloy:'alloy_port'};
let formFilled=false;
const logStorageKey='bocki-aio-live-log';
function restoreLog(){let entries=[];try{entries=JSON.parse(localStorage.getItem(logStorageKey)||'[]')}catch(error){localStorage.removeItem(logStorageKey)}if(!Array.isArray(entries)||!entries.length)return;document.getElementById('live-log').textContent=entries.join('\n')+'\n'}
function logEvent(message){const log=document.getElementById('live-log');const time=new Date().toLocaleTimeString('de-DE');const entry=`[${time}] ${message}`;if(log.textContent==='Noch keine Aktionen.')log.textContent='';log.textContent+=entry+'\n';const entries=log.textContent.trimEnd().split('\n').slice(-200);localStorage.setItem(logStorageKey,JSON.stringify(entries));log.scrollTop=log.scrollHeight}
function showError(message){document.getElementById('message').textContent=message;logEvent(message)}
window.addEventListener('unhandledrejection',event=>{showError('Verbindung zum Manager fehlgeschlagen: '+(event.reason?.message||'keine Antwort'))});
window.addEventListener('error',event=>{showError('WebUI-Fehler: '+event.message)});
document.getElementById('clear-log').addEventListener('click',()=>{localStorage.removeItem(logStorageKey);document.getElementById('live-log').textContent='Noch keine Aktionen.'});restoreLog();
function statusClass(status){const s=status.toLowerCase();if(s.includes('unhealthy')||s.includes('exited')||s==='not-created')return 'status-bad';if(s.includes('starting')||s.includes('restarting'))return 'status-warn';if(s.includes('healthy')||s.startsWith('up'))return 'status-ok';return ''}
async function state(){const response=await fetch('/api/state');const data=await response.json();document.getElementById('services').innerHTML=Object.entries(data.services).map(([name,item])=>{const link=SERVICE_LINKS[name]||(DIRECT_PORTS[name]?`http://${location.hostname}:${data.config[DIRECT_PORTS[name]]}/`:'');const webui=link?`<a href="${link}" target="_blank" rel="noreferrer">Oeffnen</a>`:'&ndash;';const actions=['start','stop','restart','update','logs'].map(action=>`<button data-service="${name}" data-action="${action}">${action}</button>`).join('');return `<tr><td><strong>${name}</strong></td><td>${webui}</td><td><small class="muted">${item.container} &middot; ${item.image}</small></td><td><span class="badge ${statusClass(item.status)}">${item.status}</span></td><td class="actions">${actions}</td></tr>`}).join('');if(data.docker_error){document.getElementById('message').textContent='Docker-Fehler: '+data.docker_error;logEvent('Docker-Fehler: '+data.docker_error)}else if(data.last_error){document.getElementById('message').textContent='Letzter Installationsfehler: '+data.last_error;logEvent('Installationsfehler: '+data.last_error)}if(!formFilled){for(const [key,value] of Object.entries(data.config)){const field=document.querySelector(`#setup [name="${key}"]`);if(field&&field.type!=='password')field.value=value}formFilled=true}}
document.getElementById('services').addEventListener('click',async event=>{const button=event.target.closest('button[data-action]');if(!button)return;const service=button.dataset.service,action=button.dataset.action;if(action==='logs'){const response=await fetch(`/api/services/${service}/logs`);const data=await response.json();document.getElementById('logs-title').textContent=`Logs: ${service}`;document.getElementById('logs-content').textContent=data.logs||data.error||'(keine Ausgabe)';document.getElementById('logs-modal').showModal();logEvent(data.error?`${service}: Log-Fehler: ${data.error}`:`Logs von ${service} geladen`);return}button.disabled=true;const response=await fetch(`/api/services/${service}/${action}`,{method:'POST'});const data=await response.json();button.disabled=false;if(data.error){document.getElementById('message').textContent=data.error;logEvent(`${service}: ${action} fehlgeschlagen: ${data.error}`);return}document.getElementById('message').textContent=action==='update'?(data.update_available?`Neues Image fuer ${service} heruntergeladen - Neustart empfohlen.`:`${service} ist bereits aktuell.`):`${service}: ${action} ausgefuehrt.`;logEvent(document.getElementById('message').textContent);state()});
document.getElementById('logs-close').addEventListener('click',()=>document.getElementById('logs-modal').close());
async function loadTelegraf(){const response=await fetch('/api/config/telegraf');const data=await response.json();if(data.error){logEvent('Telegraf-Laden fehlgeschlagen: '+data.error);return}document.getElementById('telegraf-config').value=data.config;logEvent('Telegraf-Konfiguration geladen')}
document.getElementById('telegraf-load').addEventListener('click',loadTelegraf);
document.getElementById('telegraf-save').addEventListener('click',async()=>{const button=document.getElementById('telegraf-save');button.disabled=true;const response=await fetch('/api/config/telegraf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:document.getElementById('telegraf-config').value})});const data=await response.json();button.disabled=false;if(data.error){logEvent('Telegraf-Speichern fehlgeschlagen: '+data.error);document.getElementById('message').textContent=data.error;return}logEvent('Telegraf-Konfiguration gespeichert und Telegraf neu gestartet');document.getElementById('message').textContent='Telegraf-Konfiguration gespeichert und neu gestartet.'});loadTelegraf();
document.getElementById('reinstall').addEventListener('click',async()=>{if(!confirm('Alle fuenf Fachcontainer werden entfernt und neu erstellt. Persistent gespeicherte Daten bleiben erhalten. Fortfahren?'))return;const button=document.getElementById('reinstall');button.disabled=true;document.getElementById('message').textContent='Stack wird neu erstellt...';logEvent('Stack-Neuaufbau gestartet');const response=await fetch('/api/reinstall',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});const data=await response.json();button.disabled=false;document.getElementById('message').textContent=data.error||`Stack neu erstellt. Backup: ${data.backup}`;logEvent(data.error?`Stack-Neuaufbau fehlgeschlagen: ${data.error}`:`${data.recreated.length} Dienste neu erstellt; Backup: ${data.backup}`);state()});
document.getElementById('setup').addEventListener('submit',async event=>{event.preventDefault();const payload=Object.fromEntries(new FormData(event.target));const response=await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(data.error){document.getElementById('message').textContent=data.error;logEvent(`Setup fehlgeschlagen: ${data.error}`);return}document.getElementById('message').textContent='Konfiguration erfolgreich gespeichert.';logEvent('Konfiguration erfolgreich gespeichert');document.getElementById('message').textContent+=' Containerstatus wird geprueft...';const install=await fetch('/api/install',{method:'POST'});const result=await install.json();if(result.error){document.getElementById('message').textContent=result.error;logEvent(`Installation fehlgeschlagen: ${result.error}`)}else{document.getElementById('message').textContent=`Konfiguration gespeichert; ${result.created.length} neue Dienste erstellt.`;logEvent(`Installation abgeschlossen: ${result.created.length} neue Dienste erstellt`)}state()});setInterval(state,5000);state();
</script></body></html>"""



def running_processes() -> list[str]:
    processes = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return processes
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            command = command or (entry / "comm").read_text(encoding="utf-8").strip()
            if command:
                processes.append(f"{entry.name}: {command}")
        except (OSError, UnicodeError):
            continue
    return sorted(processes, key=lambda process: int(process.split(":", 1)[0]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8800")))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("AIO_DATA_DIR", "/data")))
    args = parser.parse_args()
    manager = Manager(args.data_dir)
    Handler.manager = manager
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"Bocki Grafana AIO version={os.getenv('AIO_VERSION', 'unknown')}")
    print(f"Bocki Grafana AIO listening on {args.bind}:{args.port}")
    print(f"Manager-Login: Benutzer={manager.admin_user} Passwort={manager.admin_password}")
    print("Running processes:")
    for process in running_processes():
        print(f"  {process}")
    print("Managed services:")
    for service, details in manager._containers_by_service().items():
        print(f"  {service}: {details['status']}")
    server.serve_forever()


if __name__ == "__main__":
    main()
