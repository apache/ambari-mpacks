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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
source = ROOT / "mpacks/kyuubi/extensions/KYUUBI/1.0/services/KYUUBI/package/scripts/observer.py"
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


if __name__ == "__main__":
    unittest.main()
