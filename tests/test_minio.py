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
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
PATH = ROOT / "mpacks/minio/extensions/MINIO/1.0/services/MINIO/package/scripts/runtime.py"
spec = importlib.util.spec_from_file_location("minio_runtime_test", str(PATH))
minio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(minio)


def request():
    return {"schema_version": 1, "execution_id": "12345678-1234-4234-8234-123456789abc",
            "parameters": {"component": "check", "hostname": "minio.test", "server_host": "minio.test",
                           "api_port": "9000", "console_port": "9001", "data_directory": "/var/lib/minio/data",
                           "go_home": "/usr/local/go", "root_user": "admin_test",
                           "root_password": "private-test-secret"}}


class MinioTests(unittest.TestCase):
    def test_source_build_has_managed_caches_without_login_home(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/agent"}, clear=True):
            environment = minio.go_environment()
        self.assertNotIn("HOME", environment)
        self.assertNotIn("PYTHONPATH", environment)
        for key in ("GOCACHE", "GOMODCACHE", "GOPATH"):
            self.assertTrue(environment[key].startswith("/var/cache/ambari-mpacks/minio-go/"))
        self.assertEqual(environment["GOTOOLCHAIN"], "go1.24.8")

    def test_credentials_and_placement_must_be_explicit(self):
        value = request()["parameters"]
        self.assertEqual(minio.settings(value)[1:4], ("minio.test", 9000, 9001))
        for change in ({"root_password": "short"}, {"root_user": ""},
                       {"component": "server", "hostname": "foreign.test"},
                       {"console_port": "9000"}, {"data_directory": "/tmp/minio"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                minio.settings(dict(value, **change))

    def test_s3_result_requires_owned_identity_digest_and_cleanup(self):
        value = request()
        suffix = "a" * 32
        expected = hashlib.sha256(("ambari-mpack:" + value["execution_id"] + ":" + suffix).encode()).hexdigest()
        base = {"schema_version": 1, "execution_id": value["execution_id"], "outcome": "APPLIED",
                "stage": "verified", "bucket": "ambari-mpack-" + suffix, "object": "probe",
                "sha256": expected, "cleanup": True}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            def invoke(observed, exit_code=0):
                def run(command, **_):
                    Path(command[-1]).write_text(json.dumps(observed))
                    return SimpleNamespace(returncode=exit_code)
                with patch.object(minio, "DATA", root), patch.object(minio, "directory"), patch.object(
                        minio, "built"), patch.object(minio.os, "chown"), patch.object(
                        minio.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())), patch.object(
                        minio, "owned_file", side_effect=lambda path, content, *_: Path(path).write_text(content)), patch.object(
                        minio.subprocess, "run", side_effect=run):
                    return minio.check(value)
            self.assertEqual(invoke(base)["sha256"], expected)
            for change in ({"execution_id": "foreign"}, {"sha256": "0" * 64},
                           {"bucket": "foreign-bucket"}, {"cleanup": "true"}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    invoke(dict(base, **change))
            with self.assertRaises(minio.CheckFailure) as failure:
                invoke(dict(base, outcome="UNRESOLVED", stage="cleanup", cleanup=False), 1)
            self.assertEqual(failure.exception.observation["cleanup"], False)
            self.assertNotIn(value["parameters"]["root_password"], json.dumps(failure.exception.observation))


if __name__ == "__main__":
    unittest.main()
