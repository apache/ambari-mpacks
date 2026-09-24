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

import http.client
import json
import sys
from pathlib import Path

from observations import atomic_json, package_observation, unit_observation, validate_request


def execute(request):
    action = request["action"]
    parameters = request["parameters"]
    port = int(parameters.get("listen_port", "8080"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid endpoint port")
    observed = {"software": package_observation("nginx")}
    if action == "configure":
        target = Path("/etc/nginx/conf.d/ambari-managed.conf")
        content = ("server {\n    listen " + str(port) + ";\n"
                   "    location = /ambari-health { return 200 'ambari-nginx-v1'; }\n}\n")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".pending")
        temporary.write_text(content, encoding="ascii")
        import os
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        observed["configuration"] = {"path": str(target), "listen_port": port}
        if target.read_text(encoding="ascii") != content:
            raise RuntimeError("Nginx configuration observation does not match")
    elif action in {"start", "stop", "reload"}:
        observed["systemd"] = unit_observation("nginx.service", action)
    elif action == "health":
        observed["systemd"] = unit_observation("nginx.service")
        if observed["systemd"]["active_state"] != "active":
            raise RuntimeError("Nginx is not active")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", "/ambari-health")
            response = connection.getresponse()
            body = response.read(1024)
            if response.status != 200 or body != b"ambari-nginx-v1":
                raise RuntimeError("Nginx endpoint has no matching healthy protocol result")
            observed["endpoint"] = {"status": response.status, "identity": body.decode("ascii"), "port": port}
        finally:
            connection.close()
    elif action != "version":
        raise ValueError("Unsupported Nginx operation")
    return dict(request, outcome="APPLIED", observations=observed)


if __name__ == "__main__":
    request = validate_request(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    try:
        result = execute(request)
    except Exception as error:
        atomic_json(sys.argv[2], dict(request, outcome="UNRESOLVED",
                                     observations={"error_type": type(error).__name__}))
        raise SystemExit(1)
    atomic_json(sys.argv[2], result)
