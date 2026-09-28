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

import json
import os
import subprocess
import tempfile
from pathlib import Path

from resource_management.core.exceptions import Fail
from resource_management.libraries.script.script import Script
from managed_runtime import validate_result
from managed_service import ManagedService
from managed_topology import assigned_hosts
from observations import observer_python
from native_config import collect


def observer_environment():
    return {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}


class ManagedServiceV2(ManagedService):
    topology_fields = {}
    install_timeout = 7200

    def observe(self, action, publish=True):
        config = Script.get_config()
        command = config["commandParams"]
        request = {
            "schema_version": 1, "definition_snapshot": command["mpack_definition_snapshot"],
            "execution_id": command["mpack_execution_id"], "task_id": config.get("taskId"),
            "action": action,
            "parameters": assigned_hosts(config["configurations"][self.service + "-env"],
                                         config.get("clusterHostInfo", {}), self.topology_fields),
        }
        request["parameters"]["component"] = self.component
        request["parameters"]["native_configs"] = collect(config["configurations"], self.service)
        request["parameters"]["hostname"] = config["agentLevelParams"]["hostname"]
        with tempfile.TemporaryDirectory(prefix="ambari-" + self.service + "-") as temporary:
            os.chmod(temporary, 0o700)
            source, destination = Path(temporary) / "request.json", Path(temporary) / "result.json"
            source.write_text(json.dumps(request), encoding="utf-8")
            process = subprocess.run([observer_python(), str(Path(__file__).with_name("runtime.py")),
                str(source), str(destination)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self.install_timeout if action == "install" else 900, check=False,
                env=observer_environment())
            if not destination.is_file() or destination.stat().st_size > 1024 * 1024:
                raise Fail("Service action has no bounded structured result")
            try:
                observation = validate_result(request, json.loads(destination.read_text()))
            except (TypeError, ValueError):
                raise Fail("Service result has no matching execution identity")
            if publish:
                self.put_structured_out({"software_observation": observation})
            if process.returncode != 0 or observation["outcome"] != "APPLIED":
                raise Fail(observation.get("observations", {}).get("configuration_error") or
                           "Service action is unresolved; inspect its structured error type")
            return observation
