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
import sys
from pathlib import Path

ROLES = {"master-server", "worker-server", "api-server", "alert-server"}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ROLES:
        raise ValueError("Invalid DolphinScheduler role")
    role = sys.argv[1]
    values = json.loads(Path("/etc/dolphinscheduler/ambari/runtime.json").read_text())
    if set(values) != {"home", "java_home", "database_url", "database_user", "database_password",
                       "zookeeper", "api_port"}:
        raise ValueError("Invalid protected DolphinScheduler configuration")
    home = Path(values["home"])
    environment = dict(os.environ, JAVA_HOME=values["java_home"], DATABASE="postgresql",
                       SPRING_PROFILES_ACTIVE="postgresql", SPRING_DATASOURCE_URL=values["database_url"],
                       SPRING_DATASOURCE_USERNAME=values["database_user"],
                       SPRING_DATASOURCE_PASSWORD=values["database_password"],
                       REGISTRY_TYPE="zookeeper", REGISTRY_ZOOKEEPER_CONNECT_STRING=values["zookeeper"],
                       DOLPHINSCHEDULER_HOME=str(Path("/etc/dolphinscheduler/ambari") / role),
                       WORKER_TENANT_AUTO_CREATE="false",
                       JAVA_OPTS="-server -Duser.timezone=UTC -Xms256m -Xmx1g -XX:+ExitOnOutOfMemoryError")
    environment.pop("SERVER_PORT", None)
    if role == "api-server":
        environment["SERVER_PORT"] = str(values["api_port"])
    script = str(home / role / "bin/start.sh")
    os.execve("/bin/bash", ["/bin/bash", script], environment)


if __name__ == "__main__":
    main()
