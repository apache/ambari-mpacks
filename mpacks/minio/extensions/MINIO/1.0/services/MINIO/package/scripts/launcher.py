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
from pathlib import Path


def main():
    config = json.loads(Path("/etc/minio/ambari/runtime.json").read_text())
    if set(config) - {"environment"} != {"binary", "data", "api_port", "console_port", "root_user", "root_password"}:
        raise ValueError("Invalid protected MinIO runtime configuration")
    binary = config["binary"]
    arguments = [binary, "server", "--address", ":" + str(config["api_port"]),
                 "--console-address", ":" + str(config["console_port"]), config["data"]]
    environment = dict(os.environ, **config.get("environment", {}))
    environment.update(MINIO_ROOT_USER=config["root_user"],
                       MINIO_ROOT_PASSWORD=config["root_password"])
    os.execve(binary, arguments, environment)


if __name__ == "__main__":
    main()
