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

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
source = ROOT / "mpacks/kyuubi/extensions/KYUUBI/1.0/services/KYUUBI/package/scripts/observer.py"
sys.path.insert(0, str(source.parent))
spec = importlib.util.spec_from_file_location("kyuubi_observer", str(source))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def parameters():
    return {"kyuubi_home": "/usr/bigtop/3.3.0/usr/lib/kyuubi",
            "spark_home": "/usr/bigtop/3.3.0/usr/lib/spark",
            "java_home": "/usr/lib/jvm/java-17-openjdk",
            "hadoop_conf_dir": "/etc/hadoop/conf", "package_name": "kyuubi_3_3_0",
            "server_host": "worker1.test",
            "defaults": {"kyuubi.frontend.thrift.binary.bind.port": "10009",
                         "kyuubi.ha.addresses": "worker1.test:2181", "spark.master": "local[2]"}}


def request():
    return {"schema_version": 1, "definition_snapshot": "a" * 64,
            "execution_id": "12345678-1234-4234-8234-123456789abc",
            "task_id": 57, "action": "sql", "parameters": parameters()}


def result():
    return dict(request(), outcome="APPLIED", observations={
        "session_id": "32345678-1234-4234-8234-123456789abc",
        "operation_id": "42345678-1234-4234-8234-123456789abc",
        "engine_id": "local-1790250000000", "sum": 45, "rows": 10,
        "execution_id": request()["execution_id"], "resources_closed": True})


class KyuubiTests(unittest.TestCase):
    def test_post_command_status_does_not_replace_the_command_receipt(self):
        class Fail(Exception):
            pass
        class NotRunning(Exception):
            pass
        class Script:
            @staticmethod
            def get_config():
                values = parameters()
                return {"taskId": 57, "commandParams": {
                    "mpack_definition_snapshot": request()["definition_snapshot"],
                    "mpack_execution_id": request()["execution_id"]}, "configurations": {
                    "kyuubi-env": {key: value for key, value in values.items() if key != "defaults"},
                    "kyuubi-defaults": values["defaults"]}}
            def put_structured_out(self, observation):
                self.published = observation

        module_spec = importlib.util.spec_from_file_location("kyuubi_service_test", str(source.with_name("service.py")))
        module = importlib.util.module_from_spec(module_spec)
        with patch.dict(sys.modules, {
                "resource_management.core.exceptions": SimpleNamespace(Fail=Fail, ComponentIsNotRunning=NotRunning),
                "resource_management.libraries.script.script": SimpleNamespace(Script=Script)}):
            module_spec.loader.exec_module(module)
        service = module.Kyuubi()
        for command, health in (("start", "APPLIED"), ("stop", "UNRESOLVED")):
            def run(arguments, **options):
                observed = json.loads(Path(arguments[2]).read_text())
                outcome = health if observed["action"] == "health" else "APPLIED"
                Path(arguments[3]).write_text(json.dumps(dict(observed, outcome=outcome,
                    observations={"unit": observer.UNIT})))
                return SimpleNamespace(returncode=0 if outcome == "APPLIED" else 1)
            with self.subTest(command=command), patch.object(module.subprocess, "run", side_effect=run):
                getattr(service, command)(None)
                if health == "UNRESOLVED":
                    with self.assertRaises(NotRunning):
                        service.status(None)
                else:
                    service.status(None)
                observed = service.published["software_observation"]
                self.assertEqual(observed["action"], command)
                self.assertEqual(observed["task_id"], 57)
                self.assertEqual(observed["outcome"], "APPLIED")

    def run_jdbc(self, value, returncode=0):
        def subprocess(command, **options):
            if value is not None:
                Path(command[-1]).write_text(json.dumps(value), encoding="utf-8")
            return SimpleNamespace(returncode=returncode, stdout=b"SUCCESS noise from another operation")
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with patch.object(observer.pwd, "getpwnam", return_value=account), patch.object(
                observer.subprocess, "run", side_effect=subprocess):
            return observer.sql_observation(request())

    def test_sql_observation_checks_file_and_lineage_despite_diagnostic_noise(self):
        self.assertEqual(self.run_jdbc(result()), result()["observations"])

    def test_process_success_without_result_is_not_sql_success(self):
        with self.assertRaises(RuntimeError):
            self.run_jdbc(None)

    def test_failed_sql_preserves_bounded_diagnostic_and_rejects_foreign_lineage(self):
        diagnostic = {"error_type": "java.sql.SQLException", "stage": "DESCRIBE_SESSION",
                      "sql_state": "42S02", "vendor_code": 1}
        value = dict(result(), outcome="UNRESOLVED",
                     observations=dict(diagnostic, message="not retained"))
        for returncode in (0, 1):
            with self.assertRaises(observer.SqlObservationError) as failure:
                self.run_jdbc(value, returncode)
            self.assertEqual(failure.exception.observations, diagnostic)
        for key, foreign in (("task_id", 99), ("definition_snapshot", "b" * 64),
                             ("execution_id", "22345678-1234-4234-8234-123456789abc"),
                             ("schema_version", True), ("action", "health")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_jdbc(dict(value, **{key: foreign}), 1)

    def test_failure_result_is_not_accepted_by_default(self):
        value = dict(result(), outcome="UNRESOLVED")
        with self.assertRaises(ValueError):
            observer.validate_result(request(), value)
        self.assertEqual(observer.validate_result(request(), value, allow_unresolved=True), value)

    def test_foreign_operation_or_invalid_result_is_rejected(self):
        mutations = [
            lambda r: r.update(execution_id="22345678-1234-4234-8234-123456789abc"),
            lambda r: r.update(task_id=99),
            lambda r: r.update(definition_snapshot="b" * 64),
            lambda r: r.update(schema_version=True),
            lambda r: r["observations"].update(execution_id="22345678-1234-4234-8234-123456789abc"),
            lambda r: r["observations"].update(operation_id="not-an-operation"),
            lambda r: r["observations"].update(session_id=None),
            lambda r: r["observations"].update(engine_id=""),
            lambda r: r["observations"].update(rows=9),
            lambda r: r["observations"].update(sum=True),
            lambda r: r["observations"].update(resources_closed=False),
            lambda r: r.update(outcome="UNRESOLVED"),
        ]
        for index, mutate in enumerate(mutations):
            value = result()
            mutate(value)
            with self.subTest(case=index), self.assertRaises((ValueError, TypeError, AttributeError, RuntimeError)):
                self.run_jdbc(value)
        with self.assertRaises(RuntimeError):
            self.run_jdbc(result(), returncode=1)

    def test_runtime_parameters_reject_unsupported_or_ambiguous_inputs(self):
        for key, value in (("kyuubi_home", "/tmp/../etc"), ("java_home", "/tmp/java --option"),
                           ("package_name", "kyuubi*"), ("server_host", "server;user=other")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                observer.settings(dict(parameters(), **{key: value}))
        for key, value in (("spark.master", "spark://unknown:7077"),
                           ("kyuubi.ha.addresses", ""), ("kyuubi.frontend.thrift.binary.bind.port", "65536"),
                           ("spark.driver.memory", "1g\nkyuubi.authentication=other")):
            value_parameters = parameters()
            value_parameters["defaults"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                observer.settings(value_parameters)

    def test_client_configuration_is_owned_and_does_not_create_a_daemon(self):
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(observer, "CONFIG", root / "conf"), patch.object(
                    observer, "DATA", root / "data"), patch.object(observer, "LOGS", root / "logs"), patch.object(
                    observer.pwd, "getpwnam", return_value=account):
                observation = observer.configure(parameters(), client=True)
            self.assertTrue(observation["client_only"])
            self.assertEqual(len(observation["files"]), 2)
            content = (root / "conf/kyuubi-defaults.conf").read_text()
            self.assertIn("kyuubi.engine.type=SPARK_SQL\n", content)
            self.assertIn("spark.master=local[2]\n", content)
            self.assertEqual((root / "conf/kyuubi-defaults.conf").stat().st_mode & 0o777, 0o640)

    def test_inactive_unit_cannot_be_reported_healthy(self):
        with patch.object(observer, "package_observation", return_value={"package": "kyuubi_3_3_0"}), patch.object(
                observer, "unit_observation", return_value={"unit": observer.UNIT, "active_state": "inactive"}):
            with self.assertRaises(RuntimeError):
                observer.execute(dict(request(), action="health"))

    def test_server_unit_accepts_the_launchers_normal_sigterm_exit(self):
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        bus, manager = MagicMock(), MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = parameters()
            for key, binary in (("kyuubi_home", "kyuubi"), ("spark_home", "spark-submit"), ("java_home", "java")):
                values[key] = str(root / key)
                executable = Path(values[key]) / "bin" / binary
                executable.parent.mkdir(parents=True)
                executable.touch(mode=0o755)
            (root / "units").mkdir()
            with patch.object(observer, "CONFIG", root / "conf"), patch.object(observer, "DATA", root / "data"), patch.object(
                    observer, "LOGS", root / "logs"), patch.object(observer, "UNITS", root / "units"), patch.object(
                    observer.pwd, "getpwnam", return_value=account), patch.dict(sys.modules, {
                        "dbus": SimpleNamespace(SystemBus=lambda: bus, Interface=lambda *args: manager)}):
                result = observer.configure(values)
            unit = (root / "units" / observer.UNIT).read_text()
            self.assertIn("SuccessExitStatus=143\n", unit)
            self.assertIn("KillMode=control-group\n", unit)
            self.assertEqual(len(result["files"]), 3)
            manager.Reload.assert_called_once()
            bus.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
