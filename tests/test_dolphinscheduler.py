"""
Licensed to the Apache Software Foundation (ASF) under one or more
contributor license agreements. See the NOTICE file distributed with
this work for additional information regarding copyright ownership.
The ASF licenses this file to You under the Apache License, Version 2.0
(the "License"); you may not use this file except in compliance with
the License. You may obtain a copy of the License at
http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
PATH = ROOT / "mpacks/dolphinscheduler/extensions/DOLPHINSCHEDULER/1.0/services/DOLPHINSCHEDULER/package/scripts/runtime.py"
spec = importlib.util.spec_from_file_location("dolphinscheduler_runtime_test", str(PATH))
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)


def parameters():
    return {"component": "server", "hostname": "scheduler.test", "server_host": "scheduler.test",
            "api_port": "12345", "database_host": "database.test", "database_port": "5432",
            "database_name": "dolphinscheduler", "database_user": "scheduler",
            "database_password": "private-db-test-secret", "zookeeper_host": "zookeeper.test",
            "zookeeper_port": "2181", "admin_password": "admin-test-secret", "java_home": "/usr/lib/jvm/test"}


class DolphinSchedulerTests(unittest.TestCase):
    def test_launcher_overrides_only_the_api_http_port(self):
        launcher_path = PATH.with_name("launcher.py")
        launcher_spec = importlib.util.spec_from_file_location("ds_launcher_test", str(launcher_path))
        launcher = importlib.util.module_from_spec(launcher_spec)
        launcher_spec.loader.exec_module(launcher)
        runtime = {"home": "/opt/dolphinscheduler", "java_home": "/usr/lib/jvm/java-17-openjdk",
                   "database_url": "jdbc:postgresql://db.test/ds", "database_user": "ds",
                   "database_password": "private-test-secret", "zookeeper": "zk.test:2181", "api_port": 12345}
        for role in launcher.ROLES:
            with self.subTest(role=role), patch.object(launcher.sys, "argv", ["launcher.py", role]), patch.object(
                    launcher.Path, "read_text", return_value=json.dumps(runtime)), patch.dict(
                    launcher.os.environ, {"SERVER_PORT": "9999"}), patch.object(launcher.os, "execve") as execute:
                launcher.main()
                environment = execute.call_args.args[2]
                if role == "api-server":
                    self.assertEqual(environment["SERVER_PORT"], "12345")
                else:
                    self.assertNotIn("SERVER_PORT", environment)

    def test_settings_rejects_default_or_ambiguous_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            java = Path(temporary).resolve()
            (java / "bin").mkdir()
            (java / "bin/java").touch()
            (java / "release").write_text('JAVA_VERSION="11.0.24"\n')
            with patch.object(ds, "path_value", return_value=java):
                self.assertEqual(ds.settings(parameters())[1], "scheduler.test")
                for change in ({"admin_password": "short"}, {"database_password": "short"},
                               {"server_host": "foreign.test"}, {"api_port": "0"},
                               {"database_name": "other;drop"}):
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        ds.settings(dict(parameters(), **change))

    def test_registry_requires_one_exact_host_and_typed_port(self):
        with patch.object(ds.socket, "getaddrinfo", return_value=[(None, None, None, None, ("192.0.2.10", 0))]):
            self.assertEqual(ds.registry_rows([{"host": "192.0.2.10", "port": 1234}], "scheduler.test")["port"], 1234)
            for rows in ([], [{"host": "foreign.test", "port": 1234}],
                         [{"host": "scheduler.test", "port": True}],
                         [{"host": "scheduler.test", "port": 1234}] * 2):
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    ds.registry_rows(rows, "scheduler.test")

    def test_fresh_database_initialization_requires_schema_and_admin_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            connection = MagicMock(server_version=180000)
            cursor = connection.cursor.return_value.__enter__.return_value
            desired = hashlib.md5(parameters()["admin_password"].encode()).hexdigest()
            cursor.fetchone.side_effect = [(True,), (0,), (ds.VERSION,), (desired,)]
            cursor.fetchall.return_value = [(1, ds.DEFAULT_ADMIN_HASH)]
            cursor.rowcount = 1
            with patch.object(ds, "DATA", root), patch.object(ds, "settings", return_value=(
                    "server", "scheduler.test", "database.test", 5432, "dolphinscheduler", "scheduler",
                    "private-db-test-secret", "zookeeper.test", 2181, 12345, "admin-test-secret",
                    Path("/usr/lib/jvm/java-11-openjdk"))), patch.dict(
                    sys.modules, {"psycopg2": SimpleNamespace(connect=lambda **_: connection)}), patch.object(
                    ds.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                observed = ds.schema(parameters())
            self.assertEqual(observed["schema_version"], "3.1.9")
            self.assertEqual(json.loads((root / "database-init.json").read_text())["phase"], "COMPLETE")
            self.assertEqual(cursor.execute.call_count, 6)
            connection.close.assert_called_once()

    def test_nonempty_foreign_database_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as temporary:
            connection = MagicMock(server_version=180000)
            connection.cursor.return_value.__enter__.return_value.fetchone.side_effect = [(True,), (1,)]
            with patch.object(ds, "DATA", Path(temporary).resolve()), patch.object(ds, "database", return_value=connection), patch.object(
                    ds, "settings", return_value=("server", "scheduler.test", "database.test", 5432,
                    "dolphinscheduler", "scheduler", "private-db-test-secret", "zookeeper.test", 2181,
                    12345, "admin-test-secret", Path("/usr/lib/jvm/java-11-openjdk"))), patch.object(
                    ds.subprocess, "run") as run, self.assertRaises(ValueError):
                ds.schema(parameters())
            run.assert_not_called()

    def test_check_waits_for_registration_but_not_denied_login(self):
        settings = ("check", "scheduler.test", "database.test", 5432, "dolphinscheduler", "scheduler",
                    "private-db-test-secret", "zookeeper.test", 2181, 12345, "admin-test-secret",
                    Path("/usr/lib/jvm/java-11-openjdk"))
        session = {"sessionId": "12345678123442348234123456789abc"}
        with patch.object(ds, "settings", return_value=settings), patch.object(ds, "installed"), patch.object(
                ds, "unit_observation", return_value={"active_state": "active"}), patch.object(
                ds, "api", side_effect=[urllib.error.URLError("not listening"), session, [], [], session,
                                        [{"host": "scheduler.test", "port": 5678}],
                                        [{"host": "scheduler.test", "port": 1234}]]), patch.object(
                ds, "registry_rows", side_effect=[{"host": "scheduler.test", "port": 5678},
                                                  {"host": "scheduler.test", "port": 1234}]), patch.object(
                ds.time, "sleep"):
            self.assertEqual(ds.check(parameters())["workers"][0]["port"], 1234)
        denied = urllib.error.HTTPError("http://scheduler.test/login", 401, "Denied", {}, None)
        with patch.object(ds, "settings", return_value=settings), patch.object(ds, "installed"), patch.object(
                ds, "unit_observation", return_value={"active_state": "active"}), patch.object(
                ds, "api", side_effect=denied), patch.object(ds.time, "sleep") as sleep, self.assertRaises(
                urllib.error.HTTPError):
            ds.check(parameters())
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
