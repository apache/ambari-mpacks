"""
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements. See the NOTICE file
distributed with this work for additional information
regarding copyright ownership. The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License. You may obtain a copy of the License at

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

from resource_management.core.exceptions import Fail, ComponentIsNotRunning
from resource_management.libraries.script.script import Script
from observations import observer_python, validate_result


class Service(Script):
    def observe(self, action):
        config = Script.get_config()
        params = config["commandParams"]
        environment = config.get("configurations", {}).get("postgresql-env", {})
        request = {
            "schema_version": 1, "definition_snapshot": params["mpack_definition_snapshot"],
            "execution_id": params["mpack_execution_id"], "task_id": config.get("taskId"),
            "action": action, "parameters": environment,
        }
        with tempfile.TemporaryDirectory(prefix="ambari-service-") as directory:
            os.chmod(directory, 0o700)
            source = Path(directory) / "request.json"
            result = Path(directory) / "result.json"
            source.write_text(json.dumps(request), encoding="utf-8")
            process = subprocess.run([observer_python(), str(Path(__file__).with_name("observer.py")),
                                      str(source), str(result)], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, timeout=3600, check=False)
            if not result.is_file() or result.stat().st_size > 1024 * 1024:
                raise Fail("Service action has no bounded structured result")
            with result.open(encoding="utf-8") as output:
                observation = json.load(output)
            try:
                validate_result(request, observation)
            except ValueError as error:
                raise Fail(str(error))
            if process.returncode != 0 or observation.get("outcome") != "APPLIED":
                raise Fail("Service action did not produce a verified result")
            self.put_structured_out({"software_observation": observation})
            return observation

    def install(self, env):
        if Script.get_config().get("repositoryFile"):
            Script.repository_util.create_repo_files()
        self.install_packages(env)
        self.observe("package")

    def configure(self, env):
        self.observe("configure")

    def start(self, env):
        self.configure(env)
        self.observe("start")

    def stop(self, env):
        self.observe("stop")

    def status(self, env):
        try:
            self.observe("health")
        except Fail:
            raise ComponentIsNotRunning()

    def version_check(self, env):
        self.observe("version")

    def backup(self, env):
        self.observe("backup")

    def restore(self, env):
        self.observe("restore")


if __name__ == "__main__":
    Service().execute()
