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

from resource_management.core.exceptions import ComponentIsNotRunning, Fail
from resource_management.core.resources.accounts import Group, User
from resource_management.libraries.script.script import Script
from observations import observer_python
from managed_runtime import resolve_topology, validate_result


class ManagedService(Script):
    service = None
    component = None

    def observe(self, action, publish=True):
        config = Script.get_config()
        command = config["commandParams"]
        request = {
            "schema_version": 1, "definition_snapshot": command["mpack_definition_snapshot"],
            "execution_id": command["mpack_execution_id"], "task_id": config.get("taskId"),
            "action": action,
            "parameters": resolve_topology(self.service, config["configurations"][self.service + "-env"],
                                           config.get("clusterHostInfo", {})),
        }
        request["parameters"]["component"] = self.component
        request["parameters"]["hostname"] = config["agentLevelParams"]["hostname"]
        with tempfile.TemporaryDirectory(prefix="ambari-" + self.service + "-") as temporary:
            os.chmod(temporary, 0o700)
            source, result = Path(temporary) / "request.json", Path(temporary) / "result.json"
            source.write_text(json.dumps(request), encoding="utf-8")
            process = subprocess.run([observer_python(), str(Path(__file__).with_name("runtime.py")),
                str(source), str(result)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=1800 if action == "install" else 600, check=False)
            if not result.is_file() or result.stat().st_size > 1024 * 1024:
                raise Fail("Service action has no bounded structured result")
            try:
                observation = validate_result(request, json.loads(result.read_text()))
            except (TypeError, ValueError):
                raise Fail("Service result has no matching execution identity")
            if publish:
                self.put_structured_out({"software_observation": observation})
            if process.returncode != 0 or observation["outcome"] != "APPLIED":
                raise Fail("Service action is unresolved; inspect its structured error type")
            return observation

    def install(self, env):
        if Script.get_config().get("repositoryFile"):
            Script.repository_util.create_repo_files()
        self.install_packages(env)
        Group(self.service)
        User(self.service, gid=self.service, groups=[self.service],
             home="/var/lib/" + self.service, shell="/sbin/nologin")
        self.observe("install")

    def configure(self, env):
        self.observe("configure")

    def start(self, env):
        self.configure(env)
        self.observe("start")

    def stop(self, env):
        self.observe("stop")

    def status(self, env):
        try:
            self.observe("status", publish=False)
        except Fail:
            raise ComponentIsNotRunning()

    def version_check(self, env):
        self.observe("version")

    def initialize_database(self, env):
        self.configure(env)
        self.observe("initialize_database")

    def create_admin(self, env):
        self.observe("create_admin")

    def service_check(self, env):
        self.observe("check")
