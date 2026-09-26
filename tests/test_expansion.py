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
import io
import json
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
import managed_runtime as managed


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / relative))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


celeborn = module("celeborn_runtime_test", "mpacks/celeborn/extensions/CELEBORN/1.0/services/CELEBORN/package/scripts/runtime.py")
airflow = module("airflow_application_test", "mpacks/airflow/extensions/AIRFLOW/1.0/services/AIRFLOW/package/scripts/application.py")
airflow_runtime = module("airflow_runtime_test", "mpacks/airflow/extensions/AIRFLOW/1.0/services/AIRFLOW/package/scripts/runtime.py")


def request():
    return {"schema_version": 1, "definition_snapshot": "a" * 64,
            "execution_id": "12345678-1234-4234-8234-123456789abc",
            "task_id": 11, "action": "check", "parameters": {"database_password": "sensitive-test-value"}}


class ExpansionTests(unittest.TestCase):
    def test_observation_never_publishes_configuration_or_credentials(self):
        value = managed.result(request(), "APPLIED", {"identity": "service"})
        self.assertNotIn("parameters", value)
        self.assertNotIn("sensitive-test-value", json.dumps(value))
        self.assertEqual(managed.validate_result(request(), value), value)
        for key, foreign in (("schema_version", True), ("task_id", 12), ("execution_id", "other"),
                             ("definition_snapshot", "b" * 64), ("action", "start")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                managed.validate_result(request(), dict(value, **{key: foreign}))

    def test_topology_uses_exact_assigned_components_and_requires_one_master(self):
        observed = managed.resolve_topology("celeborn", {}, {
            "celeborn_master_hosts": ["master.test"], "celeborn_worker_hosts": ["worker2.test", "worker1.test"]})
        self.assertEqual(observed, {"master_host": "master.test", "worker_hosts": "worker1.test,worker2.test"})
        for hosts in ([], ["one.test", "two.test"], "one.test"):
            with self.subTest(hosts=hosts), self.assertRaises(ValueError):
                managed.resolve_topology("airflow", {}, {"airflow_server_hosts": hosts})
        self.assertEqual(managed.resolve_topology("airflow", {"server_host": "explicit.test"}, {}),
                         {"server_host": "explicit.test"})

    def test_runtime_paths_ports_and_hosts_reject_ambiguous_inputs(self):
        for path in ("/tmp/runtime", "/var/lib/../etc", "/var/lib/name\n", "/var/lib/space name"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                managed.path_value(path)
        for port in (True, 8080, "0", "65536", "80;id"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                managed.port_value(port)
        for host in ("server/path", "server:80", "user@server", ""):
            with self.subTest(host=host), self.assertRaises(ValueError):
                managed.host_value(host)

    def test_worker_health_rejects_foreign_unregistered_shutdown_or_wrong_port(self):
        ports = {"worker_rpc_port": 10001, "worker_push_port": 10002,
                 "worker_fetch_port": 10003, "worker_replicate_port": 10004}
        value = {"host": "worker.test", "rpcPort": 10001, "pushPort": 10002,
                 "fetchPort": 10003, "replicatePort": 10004, "isRegistered": True, "isShutdown": False}
        self.assertEqual(celeborn.validate_worker(value, "worker.test", ports), value)
        for key, bad in (("host", "other.test"), ("rpcPort", True), ("rpcPort", 1),
                         ("isRegistered", False), ("isRegistered", 1), ("isShutdown", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                celeborn.validate_worker(dict(value, **{key: bad}), "worker.test", ports)

    def test_archive_links_are_contained_and_published_after_regular_files(self):
        prefix = "apache-celeborn-0.7.0-bin/"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            archive = root / "input.tgz"
            with tarfile.open(archive, "w:gz") as stream:
                link = tarfile.TarInfo(prefix + "client/value.jar")
                link.type = tarfile.SYMTYPE
                link.linkname = "../jars/value.jar"
                stream.addfile(link)
                regular = tarfile.TarInfo(prefix + "jars/value.jar")
                regular.size = 7
                stream.addfile(regular, io.BytesIO(b"payload"))
            output = root / "output"
            output.mkdir()
            celeborn.extract(archive, output)
            self.assertEqual((output / "client/value.jar").read_bytes(), b"payload")
            for name, kind, target in (("../escape", tarfile.REGTYPE, ""),
                    (prefix + "link", tarfile.SYMTYPE, "../../escape"),
                    (prefix + "fifo", tarfile.FIFOTYPE, "")):
                with tarfile.open(archive, "w:gz") as stream:
                    entry = tarfile.TarInfo(name)
                    entry.type, entry.linkname = kind, target
                    stream.addfile(entry)
                with tempfile.TemporaryDirectory(dir=root) as target_dir, self.assertRaises(ValueError):
                    celeborn.extract(archive, Path(target_dir))
            self.assertFalse((root / "escape").exists())

    def test_airflow_requires_fresh_typed_subsystem_heartbeats(self):
        now = datetime.now(timezone.utc).isoformat()
        value = {"metadatabase": {"status": "healthy"}}
        for name in ("scheduler", "triggerer", "dag_processor"):
            value[name] = {"status": "healthy", "latest_" + name + "_heartbeat": now}
        self.assertEqual(airflow.validate_health(value), value)
        for change in (lambda r: r["scheduler"].update(status="unhealthy"),
                       lambda r: r.pop("dag_processor"),
                       lambda r: r["triggerer"].update(latest_triggerer_heartbeat="invalid"),
                       lambda r: r["scheduler"].update(latest_scheduler_heartbeat=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat())):
            broken = copy.deepcopy(value)
            change(broken)
            with self.assertRaises(ValueError):
                airflow.validate_health(broken)

    def test_airflow_rejects_nonempty_foreign_or_old_databases_before_initializing(self):
        for database, version, heads, tables in (
            ("foreign", "180000", (), ()), ("airflow", "100023", (), ()),
            ("airflow", "180000", ("old",), ()), ("airflow", "180000", (), ("orders",))):
            connection = MagicMock()
            connection.execute.return_value.scalar_one.side_effect = [version, database]
            engine = MagicMock()
            engine.connect.return_value.__enter__.return_value = connection
            db = MagicMock()
            db._get_script_object.return_value.get_heads.return_value = ["current"]
            settings = SimpleNamespace(get_engine=lambda: engine)
            migrations = SimpleNamespace(configure=lambda c: SimpleNamespace(get_current_heads=lambda: heads))
            with patch.dict(sys.modules, {
                "sqlalchemy": SimpleNamespace(inspect=lambda c: SimpleNamespace(get_table_names=lambda: tables), text=lambda s: s),
                "alembic.migration": SimpleNamespace(MigrationContext=migrations),
                "airflow": SimpleNamespace(settings=settings), "airflow.utils": SimpleNamespace(db=db)}):
                with self.subTest(database=database, heads=heads, tables=tables), self.assertRaises(ValueError):
                    airflow.database({"database_name": "airflow"}, initialize=True)
                db.initdb.assert_not_called()

    def test_airflow_health_run_rejects_foreign_acceptance(self):
        with patch.object(airflow, "json_http", side_effect=[
            {"dag_id": "ambari_mpack_health", "is_paused": False},
            {"dag_id": "other", "dag_run_id": "ambari_" + request()["execution_id"]}]):
            with self.assertRaises(ValueError):
                airflow.check_dag("http://service.test", {}, request()["execution_id"])

    def test_airflow_readiness_allows_startup_but_not_bad_credentials(self):
        parameters = {"server_host": "service.test", "api_port": "8085", "admin_username": "user", "admin_password": "test-value"}
        health = {"metadatabase": {"status": "healthy"}}
        now = datetime.now(timezone.utc).isoformat()
        for name in ("scheduler", "triggerer", "dag_processor"):
            health[name] = {"status": "healthy", "latest_" + name + "_heartbeat": now}
        with patch.object(airflow, "json_http", side_effect=[urllib.error.URLError("not listening"),
                {"access_token": "test-token"}, health]), patch.object(airflow.time, "sleep"):
            self.assertEqual(airflow.ready(parameters)[2], health)
        denied = urllib.error.HTTPError("http://service.test/auth/token", 401, "Denied", {}, None)
        with patch.object(airflow, "json_http", side_effect=denied), patch.object(airflow.time, "sleep") as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                airflow.ready(parameters)
            sleep.assert_not_called()

    def test_airflow_does_not_inherit_the_agent_python_environment(self):
        with patch.dict("os.environ", {"PYTHONPATH": "/foreign/agent", "PYTHONHOME": "/foreign/python"}):
            env = airflow_runtime.environment()
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHONHOME", env)

    def test_airflow_install_and_dependency_repair_use_only_the_isolated_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve() / "airflow"
            home.mkdir()
            identity = {"schema_version": 1, "version": airflow_runtime.VERSION,
                        "constraints_sha256": airflow_runtime.CONSTRAINTS_SHA256}
            (home / ".ambari-installed.json").write_text(json.dumps(identity))
            source = Path("/tmp/airflow-3.3.2-constraints-3.11.txt")
            if not source.is_file():
                self.skipTest("The pinned upstream constraints are not locally available")
            (home / "constraints.txt").write_bytes(source.read_bytes())
            with patch.object(airflow_runtime, "HOME", home), patch.object(
                    airflow_runtime, "directory", return_value=home.parent), patch.object(
                    airflow_runtime, "application", return_value={"software": {"apache-airflow": "3.3.2"}}), patch.object(
                    airflow_runtime, "run", side_effect=[RuntimeError("missing dependencies"), None, None]) as commands, patch.dict(
                    "os.environ", {"PYTHONPATH": "/agent/runtime", "PYTHONHOME": "/agent/python"}):
                airflow_runtime.install(request())
            self.assertEqual(len(commands.call_args_list), 3)
            self.assertIn("pip", commands.call_args_list[1].args[0])
            for call in commands.call_args_list:
                self.assertNotIn("PYTHONPATH", call.kwargs["env"])
                self.assertNotIn("PYTHONHOME", call.kwargs["env"])

    def test_airflow_rejects_boolean_schema_in_native_xcom(self):
        execution = request()["execution_id"]
        run_id = "ambari_" + execution
        dag = {"dag_id": "ambari_mpack_health", "is_paused": False}
        run = {"dag_id": dag["dag_id"], "dag_run_id": run_id, "state": "success", "conf": {"execution_id": execution}}
        task = {"task_id": "verify_execution", "dag_run_id": run_id, "state": "success"}
        xcom = {"run_id": run_id, "dag_id": dag["dag_id"], "task_id": "verify_execution", "key": "return_value",
                "value": {"schema_version": True, "execution_id": execution, "sum": 45, "rows": 10}}
        with patch.object(airflow, "json_http", side_effect=[dag, run, run, task, xcom]):
            with self.assertRaises(ValueError):
                airflow.check_dag("http://service.test", {}, execution)

    def test_airflow_reconciles_lost_run_response_by_exact_identity(self):
        execution = request()["execution_id"]
        run_id = "ambari_" + execution
        dag = {"dag_id": "ambari_mpack_health", "is_paused": False}
        run = {"dag_id": dag["dag_id"], "dag_run_id": run_id, "state": "success", "conf": {"execution_id": execution}}
        task = {"task_id": "verify_execution", "dag_run_id": run_id, "state": "success"}
        xcom = {"run_id": run_id, "dag_id": dag["dag_id"], "task_id": "verify_execution", "key": "return_value",
                "value": {"schema_version": 1, "execution_id": execution, "sum": 45, "rows": 10}}
        for failure in (urllib.error.URLError("response lost"),
                        urllib.error.HTTPError("http://service.test/dagRuns", 409, "Conflict", {}, None)):
            with self.subTest(failure=type(failure).__name__), patch.object(
                    airflow, "json_http", side_effect=[dag, failure, run, run, task, xcom]) as transport:
                observed = airflow.check_dag("http://service.test", {}, execution)
                self.assertEqual(observed["dag_run_id"], run_id)
                self.assertEqual(sum(call.args[0].endswith("/dagRuns") and len(call.args) > 1
                                     for call in transport.call_args_list), 1)
            foreign = dict(run, conf={"execution_id": "foreign"})
            with patch.object(airflow, "json_http", side_effect=[dag, failure, foreign]):
                with self.assertRaises(ValueError):
                    airflow.check_dag("http://service.test", {}, execution)

    def test_password_metadata_and_minio_release_exclusion(self):
        from xml.etree import ElementTree
        config = ROOT / "mpacks/airflow/extensions/AIRFLOW/1.0/services/AIRFLOW/configuration/airflow-env.xml"
        properties = {p.findtext("name"): p for p in ElementTree.parse(config).getroot().findall("property")}
        for name in ("database_password", "admin_password"):
            self.assertEqual(properties[name].findtext("property-type"), "PASSWORD")
            self.assertFalse(properties[name].findtext("value"))
        release = json.loads((ROOT / "release.json").read_text())
        self.assertNotIn("minio", release["packs"])
        self.assertFalse((ROOT / "mpacks/minio/mpack.json").exists())


if __name__ == "__main__":
    unittest.main()
