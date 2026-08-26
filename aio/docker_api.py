"""Minimal Docker Engine API client over the mounted Unix socket."""

from __future__ import annotations

import json
import socket
from urllib.parse import quote


class DockerApiError(RuntimeError):
    pass


class DockerClient:
    def __init__(self, socket_path: str = "/var/run/docker.sock") -> None:
        self.socket_path = socket_path

    def request(self, method: str, path: str, payload: dict | None = None) -> object:
        body = json.dumps(payload).encode() if payload is not None else b""
        request = (
            f"{method} {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
        ).encode() + body
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(10)
            connection.connect(self.socket_path)
            connection.sendall(request)
            response = b""
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                response += chunk
        finally:
            connection.close()
        headers, _, body = response.partition(b"\r\n\r\n")
        status_line = headers.splitlines()[0].decode("ascii", errors="replace")
        status = int(status_line.split()[1])
        if status >= 400:
            raise DockerApiError(body.decode("utf-8", errors="replace") or status_line)
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def containers(self) -> list[dict[str, object]]:
        result = self.request("GET", "/containers/json?all=1")
        return result if isinstance(result, list) else []

    def container_exists(self, name: str) -> bool:
        try:
            self.request("GET", f"/containers/{quote(name, safe='')}/json")
            return True
        except DockerApiError:
            return False

    def ensure_network(self, name: str) -> None:
        try:
            self.request("GET", f"/networks/{quote(name, safe='')}")
        except DockerApiError:
            self.request("POST", "/networks/create", {"Name": name, "Driver": "bridge"})

    def connect_network(self, network: str, container: str) -> None:
        try:
            self.request(
                "POST",
                f"/networks/{quote(network, safe='')}/connect",
                {"Container": container},
            )
        except DockerApiError as error:
            if "already exists" not in str(error).lower():
                raise

    def create_container(self, name: str, spec: dict) -> None:
        self.request("POST", f"/containers/create?name={quote(name, safe='')}", spec)

    def start(self, name: str) -> None:
        self.action(name, "start")

    def action(self, container_name: str, action: str) -> None:
        safe_name = quote(container_name, safe="")
        endpoint = {"start": "start", "stop": "stop", "restart": "restart"}[action]
        self.request("POST", f"/containers/{safe_name}/{endpoint}")

    def pull(self, image: str) -> None:
        repository, _, tag = image.partition(":")
        query = f"?fromImage={quote(repository, safe='')}"
        if tag:
            query += f"&tag={quote(tag, safe='')}"
        self.request("POST", f"/images/create{query}")
