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
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
PATH = ROOT / "mpacks/elasticsearch/extensions/ELASTICSEARCH/1.0/services/ELASTICSEARCH/package/scripts/runtime.py"
spec = importlib.util.spec_from_file_location("elasticsearch_runtime_test", str(PATH))
es = importlib.util.module_from_spec(spec)
spec.loader.exec_module(es)


def request():
    return {"execution_id": "12345678-1234-4234-8234-123456789abc", "parameters": {
        "component": "check", "hostname": "search.test", "node_host": "search.test",
        "http_port": "9200", "transport_port": "9300", "cluster_name": "ambari_search",
        "data_directory": "/var/lib/elasticsearch/ambari/data", "heap_size": "1G",
        "admin_password": "private-test-secret"}}


class ElasticsearchTests(unittest.TestCase):
    def test_active_process_does_not_hide_unresolved_administrator_bootstrap(self):
        value = request()
        value['parameters']['component'] = 'node'
        value['action'] = 'status'
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            with patch.object(es, "DATA", data), patch.object(es, "unit_observation", return_value={"active_state": "active"}):
                with self.assertRaises(RuntimeError):
                    es.execute(value)
                (data / "administrator.json").write_text(json.dumps({"schema_version": 1,
                    "cluster": "ambari_search", "password_sha256": hashlib.sha256(b"private-test-secret").hexdigest()}))
                self.assertEqual(es.execute(value)["systemd"]["active_state"], "active")

    def test_configuration_rejects_unsafe_identity_and_missing_credentials(self):
        self.assertEqual(es.settings(request()["parameters"])[4], "ambari_search")
        for change in ({"admin_password": "short"}, {"admin_password": "a-valid-password\n"},
                       {"cluster_name": "other;rm"},
                       {"http_port": "9300"}, {"data_directory": "/tmp/search"},
                       {"component": "node", "hostname": "foreign.test"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                es.settings(dict(request()["parameters"], **change))

    def test_index_check_accepts_only_owned_document_and_cleanup(self):
        value = request()
        index = "ambari-mpack-" + value["execution_id"].replace("-", "")
        results = [
            {"cluster_name": "ambari_search", "version": {"number": "9.5.4"}},
            {"cluster_name": "ambari_search", "timed_out": False, "status": "yellow", "number_of_nodes": 1},
            {"acknowledged": True, "index": index},
            {"_index": index, "_id": value["execution_id"], "result": "created"},
            {"_index": index, "_id": value["execution_id"], "found": True,
             "_source": {"execution_id": value["execution_id"]}},
            {"acknowledged": True},
        ]
        with patch.object(es, "api", side_effect=results), patch.object(es, "authenticate"):
            self.assertEqual(es.check(value)["cleanup"], True)
        foreign = list(results)
        foreign[4] = dict(foreign[4], _id="foreign")
        with patch.object(es, "api", side_effect=foreign), patch.object(es, "authenticate"), self.assertRaises(
                es.CheckFailure) as failure:
            es.check(value)
        self.assertEqual(failure.exception.observation,
                         {"stage": "read", "index": index, "cleanup": True})
        failed_cleanup = list(results)
        failed_cleanup[-1] = {"acknowledged": False}
        with patch.object(es, "api", side_effect=failed_cleanup), patch.object(es, "authenticate"), self.assertRaises(
                es.CheckFailure) as failure:
            es.check(value)
        self.assertEqual(failure.exception.observation["cleanup"], False)
        wrong_health = list(results)
        wrong_health[1] = dict(wrong_health[1], number_of_nodes=2)
        with patch.object(es, "api", side_effect=wrong_health), patch.object(es, "authenticate"), self.assertRaises(
                es.CheckFailure):
            es.check(value)

    def test_certificates_do_not_silently_follow_a_different_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original = es._run
            def openssl(command, **kwargs):
                executable = "/opt/homebrew/bin/openssl" if Path("/opt/homebrew/bin/openssl").is_file() else shutil.which("openssl")
                original([executable or "/usr/bin/openssl"] + command[1:], **kwargs)
            with patch.object(es, "CONF", root), patch.object(es.pwd, "getpwnam", return_value=type(
                    "Account", (), {"pw_uid": __import__("os").getuid(), "pw_gid": __import__("os").getgid()})()), patch.object(
                    es, "_run", side_effect=openssl) as run, patch.object(es, "DATA", root / "data"):
                fingerprint = es.certificate("search.test")
                self.assertEqual(es.certificate("search.test"), fingerprint)
                self.assertIn("-config", run.call_args.args[0])
                self.assertNotIn("-addext", run.call_args.args[0])
                receipt = json.loads((root / "certificate.json").read_text())
                receipt["schema_version"] = 1
                (root / "certificate.json").write_text(json.dumps(receipt))
                retained_key = (root / "node.key").read_bytes()
                es.certificate("search.test")
                self.assertEqual((root / "node.key").read_bytes(), retained_key)
                self.assertEqual(json.loads((root / "certificate.json").read_text())["schema_version"], 2)
                self.assertTrue((root / "node.pre-v2.crt").is_file())
                with self.assertRaises(ValueError):
                    es.certificate("foreign.test")


if __name__ == "__main__":
    unittest.main()
