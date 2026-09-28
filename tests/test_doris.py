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

import importlib.util
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
PATH = ROOT / "mpacks/doris/extensions/DORIS/1.0/services/DORIS/package/scripts/runtime.py"
spec = importlib.util.spec_from_file_location("doris_runtime_test", str(PATH))
doris = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doris)


def parameters():
    return {"component": "check", "hostname": "fe.test", "fe_host": "fe.test", "be_host": "be.test",
            "fe_http_port": "8030", "fe_rpc_port": "9020", "fe_query_port": "9030",
            "fe_edit_log_port": "9010", "be_port": "9060", "be_http_port": "8040",
            "be_heartbeat_port": "9050", "be_brpc_port": "8060", "java_home": "/usr/lib/jvm/java-17-openjdk",
            "fe_heap_size": "2G", "be_memory_limit": "2G", "root_password": "private-test-secret"}


def settings():
    return ("check", "fe.test", "be.test", "fe.test", {"fe_http_port": 8030,
            "fe_rpc_port": 9020, "fe_query_port": 9030, "fe_edit_log_port": 9010,
            "be_port": 9060, "be_http_port": 8040, "be_heartbeat_port": 9050,
            "be_brpc_port": 8060}, Path("/usr/lib/jvm/java-17-openjdk"), "2G", "2G", "private-test-secret")


class DorisTests(unittest.TestCase):
    def test_active_fe_is_not_started_until_owned_bootstrap_completes(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            (data / "fe").mkdir()
            identity = {"phase": "PENDING", "fe_host": "fe.test",
                        "root_password_sha256": hashlib.sha256(b"private-test-secret").hexdigest()}
            marker = data / "fe/identity.json"
            marker.write_text(json.dumps(identity))
            with patch.object(doris, "DATA", data), patch.object(doris, "settings", return_value=("fe",)+settings()[1:]), patch.object(
                    doris, "unit_observation", return_value={"active_state": "active"}):
                with self.assertRaises(RuntimeError):
                    doris.execute({"parameters": {}, "action": "status"})
                marker.write_text(json.dumps(dict(identity, phase="COMPLETE")))
                self.assertEqual(doris.execute({"parameters": {}, "action": "status"})["systemd"]["active_state"], "active")

    def test_configure_preserves_data_directories_and_nested_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home, data = root / "software", root / "data"
            for relative in ("fe/bin", "fe/conf/ssl", "fe/lib", "fe/meta"):
                (home / relative).mkdir(parents=True)
            (home / "fe/bin/start_fe.sh").write_text("#!/bin/bash\n")
            (home / "fe/conf/fe.conf").write_text("# upstream\n")
            (home / "fe/conf/ssl/example.conf").write_text("trusted=true\n")
            def directory(path, *_):
                Path(path).mkdir(parents=True, exist_ok=True)
                return Path(path)
            values = ("fe",) + settings()[1:]
            with patch.object(doris, "HOME", home), patch.object(doris, "DATA", data), patch.object(
                    doris, "settings", return_value=values), patch.object(doris, "installed"), patch.object(
                    doris, "directory", side_effect=directory), patch.object(
                    doris, "owned_file", side_effect=lambda path, content, *_: Path(path).write_text(content)), patch.object(
                    doris, "unit"), patch.object(doris, "reload_units"):
                doris.configure(parameters())
            self.assertFalse((data / "fe/meta").is_symlink())
            self.assertTrue((data / "fe/lib").is_symlink())
            self.assertEqual((data / "fe/conf/ssl/example.conf").read_text(), "trusted=true\n")

    def test_ports_placement_and_password_are_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            java = Path(temporary).resolve()
            (java / "bin").mkdir()
            (java / "bin/java").touch()
            (java / "release").write_text('JAVA_VERSION="17.0.16"\n')
            with patch.object(doris, "path_value", return_value=java):
                self.assertEqual(doris.settings(parameters())[1:3], ("fe.test", "be.test"))
                for change in ({"root_password": "short"}, {"fe_host": "foreign.test", "component": "fe"},
                               {"fe_query_port": "0"}, {"be_memory_limit": "1G"},
                               {"fe_host": "same.test", "be_host": "same.test", "fe_http_port": "8040"}):
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        doris.settings(dict(parameters(), **change))

    def test_system_java_alias_resolves_before_no_link_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real = root / "java-17-runtime"
            (real / "bin").mkdir(parents=True)
            (real / "bin/java").touch()
            (real / "release").write_text('JAVA_VERSION="17.0.16"\n')
            alias = root / "java-17-openjdk"
            alias.symlink_to(real)
            with patch.object(doris, "path_value", side_effect=lambda value, *_: Path(value)):
                self.assertEqual(doris.settings(dict(parameters(), java_home=str(alias)))[5], real)

    def test_inventory_uses_exact_fe_be_and_registration_ports(self):
        frontend = {"Host": "fe.test", "Alive": "true", "IsMaster": "true", "EditLogPort": "9010"}
        backend = {"Host": "be.test", "Alive": "true", "HeartbeatPort": "9050", "HttpPort": "8040"}
        with patch.object(doris, "_addresses", side_effect=lambda host: {host}):
            self.assertEqual(doris.validate_nodes([frontend], [backend], "fe.test", "be.test",
                                                   settings()[4])["be"], "be.test")
            for wrong_fe, wrong_be in ((dict(frontend, Host="foreign.test"), backend),
                                       (frontend, dict(backend, Alive="false")),
                                       (frontend, dict(backend, HeartbeatPort="9051"))):
                with self.subTest(fe=wrong_fe, be=wrong_be), self.assertRaises(ValueError):
                    doris.validate_nodes([wrong_fe], [wrong_be], "fe.test", "be.test", settings()[4])

    def test_owned_sql_roundtrip_rejects_wrong_result_or_failed_cleanup(self):
        value = {"execution_id": "12345678-1234-4234-8234-123456789abc", "parameters": parameters()}
        rows = [[{"Host": "fe.test"}], [{"Host": "be.test"}], [], [], [],
                [{"row_count": 1, "value_sum": 42}], [], []]
        def run(observed):
            client = MagicMock()
            with patch.object(doris, "settings", return_value=settings()), patch.object(
                    doris, "connection", return_value=client), patch.object(doris, "query", side_effect=observed), patch.object(
                    doris, "validate_nodes", return_value={"fe": "fe.test", "be": "be.test"}):
                return doris.check(value)
        self.assertEqual(run(rows)["value_sum"], 42)
        wrong = list(rows)
        wrong[5] = [{"row_count": 2, "value_sum": 42}]
        with self.assertRaises(doris.CheckFailure) as failure:
            run(wrong)
        self.assertEqual(failure.exception.observation["stage"], "read")
        self.assertEqual(failure.exception.observation["cleanup"], True)
        failed_cleanup = list(rows)
        failed_cleanup[-1] = [{"Database": "ambari_mpack_12345678123442348234123456789abc"}]
        with self.assertRaises(doris.CheckFailure) as failure:
            run(failed_cleanup)
        self.assertEqual(failure.exception.observation["cleanup"], False)

    def test_initial_root_password_recovery_uses_exact_auth_error_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "fe").mkdir()
            identity = {"schema_version": 1, "version": "4.1.4", "fe_host": "fe.test",
                        "root_password_sha256": hashlib.sha256(b"private-test-secret").hexdigest(), "phase": "PENDING"}
            (root / "fe/identity.json").write_text(json.dumps(identity))
            access_denied = type("OperationalError", (Exception,), {})
            empty = MagicMock()
            authenticated = MagicMock()
            with patch.object(doris, "DATA", root), patch.object(doris, "settings", return_value=settings()), patch.dict(
                    sys.modules, {"pymysql": SimpleNamespace(err=SimpleNamespace(OperationalError=access_denied))}), patch.object(
                    doris, "connection", side_effect=[access_denied(1045, "diagnostic noise"), empty, authenticated]):
                self.assertEqual(doris.bootstrap_fe(parameters())["phase"], "COMPLETE")
            self.assertEqual(json.loads((root / "fe/identity.json").read_text())["phase"], "COMPLETE")
            empty.cursor.return_value.__enter__.return_value.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
