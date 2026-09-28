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
from resource_management.libraries.script.script import Script
from observations import observer_python
from results import validate_result
from native_config import collect, properties


class Kyuubi(Script):
    def observe(self, action, publish=True):
        config = Script.get_config()
        command = config["commandParams"]
        parameters = dict(config["configurations"]["kyuubi-env"])
        parameters["defaults"] = dict(config["configurations"]["kyuubi-defaults"])
        parameters["native_configs"] = collect(config["configurations"], "kyuubi")
        if not properties(parameters, "kyuubi-defaults").get("kyuubi.ha.addresses"):
            hosts = config.get("clusterHostInfo", {}).get("zookeeper_hosts", [])
            if not hosts:
                raise Fail("Kyuubi requires an explicit or assigned ZooKeeper quorum")
            port = config.get("configurations", {}).get("zoo.cfg", {}).get("clientPort", "2181")
            parameters["zookeeper_quorum"] = ",".join(host + ":" + str(port) for host in hosts)
        request = {
            "schema_version": 1, "definition_snapshot": command["mpack_definition_snapshot"],
            "execution_id": command["mpack_execution_id"], "task_id": config.get("taskId"),
            "action": action, "parameters": parameters,
        }
        with tempfile.TemporaryDirectory(prefix="ambari-kyuubi-") as directory:
            os.chmod(directory, 0o700)
            source, result = Path(directory) / "request.json", Path(directory) / "result.json"
            source.write_text(json.dumps(request), encoding="utf-8")
            process = subprocess.run(
                [observer_python(), str(Path(__file__).with_name("observer.py")), str(source), str(result)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=540, check=False)
            if not result.is_file() or result.stat().st_size > 1024 * 1024:
                raise Fail("Kyuubi action has no bounded structured result")
            try:
                observation = validate_result(request, json.loads(result.read_text(encoding="utf-8")),
                                              allow_unresolved=True)
            except (ValueError, TypeError) as error:
                raise Fail(str(error))
            if publish:
                self.put_structured_out({"software_observation": observation})
            if process.returncode != 0 or observation["outcome"] != "APPLIED":
                raise Fail("Kyuubi action did not complete")
            return observation

    def install(self, env):
        if Script.get_config().get("repositoryFile"):
            Script.repository_util.create_repo_files()
        self.install_packages(env)
        self.observe("version")

    def configure(self, env):
        self.observe("configure")

    def start(self, env):
        self.configure(env)
        self.observe("start")

    def stop(self, env):
        self.observe("stop")

    def status(self, env):
        try:
            self.observe("health", publish=False)
        except Fail:
            raise ComponentIsNotRunning()

    def version_check(self, env):
        self.observe("version")

    def sql_check(self, env):
        self.observe("sql")


if __name__ == "__main__":
    Kyuubi().execute()
