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
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
import native_config as native


def parameters(types):
    return {"native_configs": {"schema_version": 1, "types": types}}


def module(name):
    path = ROOT / "mpacks" / name / "extensions" / name.upper() / "1.0/services" / name.upper() / "package/scripts/runtime.py"
    spec = importlib.util.spec_from_file_location(name + "_native_test", str(path))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class TrinoNativeConfigurationTests(unittest.TestCase):
    def test_trino_renders_custom_configs_removes_catalogs_and_recovers_after_conflict(self):
        runtime = module("trino")
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            request = parameters({"trino-config": {"query.max-history": "37"},
                                  "trino-node": {"node.internal-address-source": "HOSTNAME"},
                                  "trino-catalogs": {"content": '{"tpch":{"connector.name":"tpch"},"memory":{"connector.name":"memory"}}'}})
            with patch.object(runtime, "settings", return_value=("coordinator", "node.test", [], "node.test", 8086, Path("/java"), "2G", "test")), patch.object(
                    runtime, "installed"), patch.object(runtime, "CONF", root / "conf"), patch.object(
                    runtime, "DATA", root / "data"), patch.object(runtime, "LOGS", root / "logs"), patch.object(
                    runtime, "unit"), patch.object(runtime, "reload_units"), patch("pwd.getpwnam", return_value=account):
                runtime.configure(request)
                conf = root / "conf"
                self.assertIn("query.max-history=37\n", (conf / "config.properties").read_text())
                self.assertTrue((conf / "catalog/memory.properties").is_file())
                self.assertEqual((conf / "catalog/memory.properties").stat().st_mode & 0o777, 0o600)
                identity = (root / "data/node-id").read_text()
                before = (conf / "config.properties").read_bytes()
                request["native_configs"]["types"]["trino-config"]["coordinator"] = "false"
                with self.assertRaises(native.ConfigurationError):
                    runtime.configure(request)
                self.assertEqual((conf / "config.properties").read_bytes(), before)
                del request["native_configs"]["types"]["trino-config"]["coordinator"]
                del request["native_configs"]["types"]["trino-catalogs"]
                runtime.configure(request)
                self.assertFalse((conf / "catalog/memory.properties").exists())
                self.assertEqual((root / "data/node-id").read_text(), identity)
                request["native_configs"]["types"]["trino-catalogs"] = {"content": '{"tpch":{"connector.name":"tpch"},"memory":{"connector.name":"memory"}}'}
                original_write = runtime.owned_file
                def interrupted(path, *args, **kwargs):
                    if Path(path).name == "memory.properties":
                        raise OSError("Interrupted configuration write")
                    return original_write(path, *args, **kwargs)
                with patch.object(runtime, "owned_file", side_effect=interrupted), self.assertRaises(OSError):
                    runtime.configure(request)
                runtime.configure(request)
                self.assertTrue((conf / "catalog/memory.properties").is_file())


if __name__ == "__main__":
    unittest.main()
