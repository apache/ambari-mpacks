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
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))


class ManagedServiceV2Tests(unittest.TestCase):
    def test_observer_gets_clean_python_environment_and_matching_result(self):
        config = {"commandParams": {"mpack_definition_snapshot": "a" * 64,
                  "mpack_execution_id": "12345678-1234-4234-8234-123456789abc"},
                  "taskId": 12, "configurations": {"test-env": {}},
                  "agentLevelParams": {"hostname": "node.test"}, "clusterHostInfo": {}}
        spec = importlib.util.spec_from_file_location("managed_service_v2_test", str(ROOT / "shared/managed_service_v2.py"))
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "resource_management.core.exceptions": SimpleNamespace(Fail=RuntimeError),
            "resource_management.libraries.script.script": SimpleNamespace(Script=SimpleNamespace(get_config=lambda: config)),
            "managed_service": SimpleNamespace(ManagedService=object),
        }):
            spec.loader.exec_module(module)
        observed = []
        def run(command, **kwargs):
            self.assertNotIn("PYTHONPATH", kwargs["env"])
            self.assertNotIn("PYTHONHOME", kwargs["env"])
            self.assertEqual(kwargs["env"]["HTTPS_PROXY"], "http://proxy.test:7890")
            request = json.loads(Path(command[-2]).read_text())
            result = {key: request[key] for key in ("schema_version", "definition_snapshot", "execution_id", "task_id", "action")}
            result.update(outcome="APPLIED", observations={"unit": "active"})
            Path(command[-1]).write_text(json.dumps(result))
            return SimpleNamespace(returncode=0)
        instance = module.ManagedServiceV2()
        instance.service, instance.component = "test", "node"
        instance.put_structured_out = observed.append
        with patch.dict(os.environ, {"PYTHONPATH": "/agent/python39", "PYTHONHOME": "/agent",
                                     "HTTPS_PROXY": "http://proxy.test:7890"}), patch.object(
                module, "observer_python", return_value="/usr/libexec/platform-python"), patch.object(
                module.subprocess, "run", side_effect=run):
            self.assertEqual(instance.observe("status")["task_id"], 12)
        self.assertEqual(observed[0]["software_observation"]["outcome"], "APPLIED")


if __name__ == "__main__":
    unittest.main()
