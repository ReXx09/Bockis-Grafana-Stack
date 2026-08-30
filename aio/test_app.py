import json
import tempfile
import unittest
from pathlib import Path

from aio.app import Handler, Manager, running_processes
from aio.docker_api import DockerApiError, DockerClient
from aio.filterlog import FilterlogParseError, parse_filterlog
from aio.services import ALLOWED_ACTIONS, SERVICE_DEFINITIONS


class ManagerTests(unittest.TestCase):
    class FakeDocker:
        def __init__(self, socket_path):
            self.socket_path = socket_path
            self.calls = []

        def containers(self):
            return [{"Names": ["/bocki-aio-grafana"], "Status": "Up 2 minutes", "Id": "abc123"}]

        def action(self, container_name, action):
            self.calls.append((container_name, action))

        def pull(self, image):
            self.calls.append(("pull", image))

        def ensure_network(self, name):
            self.calls.append(("network", name))

        def container_exists(self, name):
            return False

        def create_container(self, name, spec):
            self.calls.append(("create", name, spec))

        def start(self, name):
            self.calls.append(("start", name))

        def inspect(self, name):
            if name != "bocki-aio-grafana":
                raise DockerApiError("no such container")
            return {"Id": "abc123", "State": {"Status": "running"}, "NetworkSettings": {"Networks": {"bocki-monitoring": {"IPAddress": "172.30.0.7"}}}}

    def test_fresh_state_contains_only_known_services(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Manager(Path(directory)).state()

        self.assertFalse(state["configured"])
        self.assertEqual(set(state["services"]), set(SERVICE_DEFINITIONS))
        self.assertTrue(set(state["services"]).isdisjoint({"postgres", "random-container"}))

    def test_docker_client_decodes_chunked_responses(self):
        body = b"3\r\n[1,\r\n4\r\n2,3]\r\n0\r\n\r\n"

        self.assertEqual(DockerClient._decode_chunked(body), b"[1,2,3]")

    def test_running_processes_returns_pid_prefixed_entries(self):
        processes = running_processes()

        self.assertIsInstance(processes, list)
        self.assertTrue(all(": " in process for process in processes))

    def test_setup_requires_both_passwords(self):
        with self.assertRaises(ValueError):
            Handler._validate_setup({"grafana_admin_password": "only-one"})

    def test_actions_are_explicitly_limited(self):
        self.assertEqual(ALLOWED_ACTIONS, {"start", "stop", "restart", "update"})

    def test_state_reads_only_managed_container_names(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "docker.sock"
            socket_path.touch()
            manager = Manager(Path(directory) / "data", self.FakeDocker(str(socket_path)))

            self.assertEqual(manager.state()["services"]["grafana"]["status"], "Up 2 minutes")
            self.assertEqual(manager.state()["services"]["loki"]["status"], "not-created")

    def test_service_action_maps_to_known_container(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "docker.sock"
            socket_path.touch()
            docker = self.FakeDocker(str(socket_path))
            manager = Manager(Path(directory) / "data", docker)

            result = manager.service_action("grafana", "restart")

            self.assertEqual(result["status"], "requested")
            self.assertEqual(docker.calls, [("bocki-aio-grafana", "restart")])

    def test_proxy_uses_managed_container_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "docker.sock"
            socket_path.touch()
            manager = Manager(Path(directory) / "data", self.FakeDocker(str(socket_path)))

            self.assertEqual(manager.proxy_target("/grafana/"), ("172.30.0.7", 3000, "/"))

    def test_proxy_falls_back_to_managed_container_name(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "docker.sock"
            socket_path.touch()
            docker = self.FakeDocker(str(socket_path))
            docker.inspect = lambda name: {"NetworkSettings": {"Networks": {}}}
            manager = Manager(Path(directory) / "data", docker)

            self.assertEqual(manager.proxy_target("/grafana/"), ("bocki-aio-grafana", 3000, "/"))

    def test_install_creates_all_services_and_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            socket_path = root / "docker.sock"
            socket_path.touch()
            docker = self.FakeDocker(str(socket_path))
            manager = Manager(root / "data", docker)
            manager.save_config({"grafana_admin_password": "grafana", "influx_admin_password": "influx"})

            result = manager.install_stack()

            self.assertEqual(set(result["created"]), set(SERVICE_DEFINITIONS))
            self.assertTrue((root / "data" / "generated" / "telegraf.conf").exists())
            dashboard = root / "data" / "generated" / "opnsense-firewall-v1.json"
            self.assertEqual(json.loads(dashboard.read_text(encoding="utf-8"))["uid"], "bocki-opnsense-firewall")
            alloy = (root / "data" / "generated" / "alloy-config.alloy").read_text(encoding="utf-8")
            self.assertIn('loki.process "filterlog"', alloy)
            self.assertIn("stage.structured_metadata", alloy)
            self.assertEqual(sum(call[0] == "create" for call in docker.calls), 5)

            specs = [call[2] for call in docker.calls if call[0] == "create"]
            checked_specs = [spec for spec in specs if spec["Image"] != "telegraf:1.34"]
            self.assertTrue(all("Healthcheck" in spec for spec in checked_specs))
            loki_spec = next(spec for spec in specs if spec["Image"] == "grafana/loki:3.4.2")
            self.assertEqual(loki_spec["User"], "0")

    def test_filterlog_parser_extracts_firewall_event(self):
        message = "<134>Aug 25 12:00:00 firewall filterlog: 1,,,1000000103,igb0,match,block,in,4,0x0,,64,0,0,none,17,udp,60,203.0.113.10,192.0.2.20,4444,443"

        event = parse_filterlog(message)

        self.assertEqual(event.action, "block")
        self.assertEqual(event.interface, "igb0")
        self.assertEqual(event.source_port, 4444)
        self.assertEqual(event.destination_port, 443)

    def test_filterlog_parser_rejects_invalid_ip(self):
        message = "1,,,tracker,igb0,match,pass,in,4,0x0,,64,0,0,none,6,tcp,60,not-an-ip,192.0.2.20,1,2"

        with self.assertRaises(FilterlogParseError):
            parse_filterlog(message)


if __name__ == "__main__":
    unittest.main()
