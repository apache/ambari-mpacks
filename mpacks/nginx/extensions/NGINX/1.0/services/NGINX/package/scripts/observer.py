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
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from observations import atomic_json, package_observation, platform_identity, unit_observation, validate_request
from content_files import render, transaction, result as action_result
from native_config import ConfigurationError

ROOT = Path("/etc/nginx")


def configure(request, activate=None):
    parameters = request["parameters"]
    port = int(parameters.get("listen_port", "8080"))
    content = render(parameters, "nginx-conf", {"listen_port": port,
        "nginx_user": "nginx" if platform_identity() == ("rocky", "8") else "www-data"})
    if content is None:
        return None
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    health_content = ("server {\n    listen " + str(port) + ";\n"
                      "    location = /ambari-health { return 200 'ambari-nginx-v1'; }\n"
                      "    location = /ambari-config { return 200 '" + digest + "'; }\n}\n")
    (ROOT / "conf.d").mkdir(exist_ok=True)
    def validate(staged):
        check = subprocess.run(["/usr/sbin/nginx", "-t", "-p", str(ROOT) + "/",
                                "-c", str(staged["nginx.conf"])],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        if check.returncode != 0:
            raise ConfigurationError("nginx.conf failed nginx -t; existing configuration was preserved")
    with transaction(ROOT / "conf.d", {"ambari-managed.conf": health_content}, lambda staged: None, "root"):
        with transaction(ROOT, {"nginx.conf": content}, validate, "root") as files:
            observed = {"files": files}
            if activate:
                observed["systemd"] = unit_observation("nginx.service", activate)
                observed["health"] = health(port, digest)
            return observed


def health(port, expected=None):
    deadline = time.monotonic() + 30
    while expected:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("GET", "/ambari-config")
            response = connection.getresponse()
            if response.status == 200 and response.read(256) == expected.encode("ascii"):
                break
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        if time.monotonic() >= deadline:
            raise RuntimeError("Nginx has not activated the requested configuration digest")
        time.sleep(0.2)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", "/ambari-health")
        response = connection.getresponse()
        body = response.read(1024)
        if response.status != 200 or body != b"ambari-nginx-v1":
            raise RuntimeError("Nginx endpoint has no matching healthy protocol result")
        return {"status": response.status, "identity": body.decode("ascii"), "port": port, "configuration_sha256": expected}
    finally:
        connection.close()


def execute(request):
    action = request["action"]
    parameters = request["parameters"]
    port = int(parameters.get("listen_port", "8080"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid endpoint port")
    observed = {"software": package_observation("nginx")}
    if action in {"configure", "start", "reload"}:
        try:
            configured = configure(request, action if action != "configure" else None)
        except Exception:
            if action == "reload":
                unit_observation("nginx.service", "reload")
            elif action == "start":
                unit_observation("nginx.service", "stop")
            raise
        if configured is not None:
            observed["configuration"] = configured
            return action_result(request, "APPLIED", observed)
        if action in {"start", "reload"}:
            execute(dict(request, action="configure"))
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
    return action_result(request, "APPLIED", observed)


if __name__ == "__main__":
    request = validate_request(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    try:
        result = execute(request)
    except Exception as error:
        details = {"error_type": type(error).__name__}
        if isinstance(error, ConfigurationError):
            details["configuration_error"] = str(error)
        atomic_json(sys.argv[2], action_result(request, "UNRESOLVED",
                                     details))
        raise SystemExit(1)
    atomic_json(sys.argv[2], result)
