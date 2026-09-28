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
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from managed_runtime import directory, host_value, json_http, main, no_links, owned_file, path_value, port_value, reload_units, unit
from observations import unit_observation
from verified_archive import install_archive, verify_install
from native_config import catalogs, content, jvm_options, properties, render_properties

VERSION = "483"
SHA512 = "5b6920dcb807608e13bb0f2d6d062233ffafe627d035ac37c37da28dbfd0933f10a37871505247ef65e1f973f503b341f9038d0a52773e0ceb0dcf6d037fb6ee"
URL = "https://github.com/trinodb/trino/releases/download/483/trino-server-483.tar.gz"
REQUIRED = ["bin/launcher", "bin/launcher.properties", "bin/linux-arm64/launcher",
            "lib/io.trino_trino-main-483.jar"]
HOME = Path("/opt/ambari-mpacks/trino/483")
CONF = Path("/etc/trino/ambari")
DATA = Path("/var/lib/trino")
LOGS = Path("/var/log/trino")


def settings(parameters):
    role = parameters["component"]
    if role not in {"coordinator", "worker", "check"}:
        raise ValueError("Unknown Trino component")
    coordinator = host_value(parameters["coordinator_host"])
    workers = [host_value(item) for item in parameters.get("worker_hosts", "").split(",") if item]
    if len(workers) != len(set(workers)) or coordinator in workers:
        raise ValueError("Trino coordinator and worker assignments overlap")
    hostname = host_value(parameters["hostname"])
    if role == "coordinator" and hostname != coordinator or role == "worker" and hostname not in workers:
        raise ValueError("Trino component placement differs from the assigned hosts")
    port = port_value(parameters["http_port"])
    java = path_value(parameters["java_home"], ("/usr/lib/jvm/",))
    no_links(java)
    release = java / "release"
    if not release.is_file() or not (java / "bin/java").is_file():
        raise ValueError("A Java 25 installation is required")
    versions = re.findall(r'^JAVA_VERSION="(25\.[0-9.]+)"$', release.read_text(), re.MULTILINE)
    if len(versions) != 1:
        raise ValueError("Trino 483 requires Java 25")
    heap = parameters["heap_size"]
    if not isinstance(heap, str) or not re.fullmatch(r"[2-9][0-9]*G", heap):
        raise ValueError("Trino heap must be at least 2G")
    environment = parameters["node_environment"]
    if not isinstance(environment, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_]*", environment):
        raise ValueError("Invalid Trino node environment")
    return role, coordinator, workers, hostname, port, java, heap, environment


def installed():
    return verify_install(HOME, "trino", VERSION, SHA512, REQUIRED)


def configure(parameters):
    role, coordinator, workers, hostname, port, java, heap, environment = settings(parameters)
    if role == "check":
        raise ValueError("A service check cannot configure a node")
    options = properties(parameters, "trino-config", {
        "coordinator": "true" if role == "coordinator" else "false",
        "http-server.http.port": port, "discovery.uri": "http://" + coordinator + ":" + str(port)},
        {"node-scheduler.include-coordinator": "true"} if role == "coordinator" else {},
        reserved=("http-server.authentication.", "http-server.https.", "internal-communication."))
    if role == "worker":
        options.pop("node-scheduler.include-coordinator", None)
    jvm = ["-Xmx" + heap] + jvm_options(parameters, "trino-jvm",
        "-server\n-XX:+UseG1GC\n-XX:+ExitOnOutOfMemoryError\n--add-modules=jdk.incubator.vector\n")
    catalog_files = catalogs(parameters)
    logging = render_properties(properties(parameters, "trino-log", defaults={"io.trino": "INFO"}))
    installed()
    for path in (CONF, CONF / "catalog", DATA, LOGS):
        directory(path, "trino")
    identity = DATA / "node-id"
    no_links(identity)
    if not identity.exists():
        owned_file(identity, str(uuid.uuid4()) + "\n", "trino", 0o600)
    node_id = identity.read_text().strip()
    if str(uuid.UUID(node_id)) != node_id:
        raise ValueError("Retained Trino node identity is invalid")
    node = properties(parameters, "trino-node", {
        "node.environment": environment, "node.id": node_id, "node.data-dir": str(DATA)})
    owned_file(CONF / "node.properties", render_properties(node), "trino")
    owned_file(CONF / "jvm.config", "\n".join(jvm) + "\n", "trino")
    owned_file(CONF / "config.properties", render_properties(options), "trino")
    owned_file(CONF / "log.properties", logging, "trino")
    inventory = CONF / "catalogs.json"
    no_links(inventory)
    previous = json.loads(inventory.read_text()) if inventory.exists() else ["tpch.properties"]
    if not isinstance(previous, list) or any(not isinstance(n, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*\.properties", n) for n in previous):
        raise ValueError("Invalid managed catalog inventory")
    for name, value in catalog_files.items():
        target = CONF / "catalog" / name
        no_links(target)
        if target.exists() and name not in previous:
            raise ValueError("An unmanaged catalog exists; reconcile it before configuration")
    # Reserve validated names before writes so a partial write remains retryable.
    owned_file(inventory, json.dumps(sorted(set(previous) | set(catalog_files))), "trino", 0o600)
    for name, value in catalog_files.items():
        owned_file(CONF / "catalog" / name, value, "trino", 0o600)
    for name in set(previous) - set(catalog_files):
        target = CONF / "catalog" / name
        no_links(target)
        if target.exists():
            target.unlink()
    owned_file(inventory, json.dumps(sorted(catalog_files)), "trino", 0o600)
    unit("ambari-trino.service", "trino", HOME / "bin/launcher", {"JAVA_HOME": str(java)}, DATA,
         "-etc-dir " + str(CONF) + " -data-dir " + str(DATA) + " run")
    reload_units()
    return {"role": role, "node_id": node_id, "coordinator": coordinator, "http_port": port}


def validate_info(value, version, environment, coordinator, require_ready=True):
    if (not isinstance(value, dict) or value.get("state") not in {"ACTIVE", "INACTIVE"}
            or type(value.get("starting")) is not bool or value.get("coordinator") is not coordinator
            or value.get("environment") != environment
            or not isinstance(value.get("nodeVersion"), dict)
            or value["nodeVersion"].get("version") != version
            or not isinstance(value.get("nodeId"), str) or not value["nodeId"]):
        raise ValueError("Trino node identity or readiness differs")
    if require_ready and (value["state"] != "ACTIVE" or value["starting"]):
        raise ValueError("Trino node is not ready")
    return {key: value[key] for key in ("nodeId", "state", "environment", "coordinator")}


def ready_info(url, environment, coordinator):
    deadline = time.monotonic() + 120
    while True:
        try:
            value = json_http(url)
            observed = validate_info(value, VERSION, environment, coordinator, require_ready=False)
            if value["state"] == "ACTIVE" and value["starting"] is False:
                return observed
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Trino node readiness remains unresolved")
        time.sleep(2)


def statement(url, query):
    origin = urllib.parse.urlsplit(url)
    headers = {"X-Trino-User": "ambari_mpack", "X-Trino-Source": "ambari-mpack",
               "Accept": "application/json", "Content-Type": "text/plain"}
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    current = url + "/v1/statement"
    data = query.encode("utf-8")
    query_id = None
    rows = []
    deadline = time.monotonic() + 90
    for _ in range(100):
        request = urllib.request.Request(current, data=data, headers=headers)
        with opener.open(request, timeout=15) as response:
            payload = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(payload) > 1024 * 1024:
                raise ValueError("Invalid bounded Trino query response")
        value = json.loads(payload)
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
            raise ValueError("Missing Trino query identity")
        if query_id is None:
            query_id = value["id"]
        if value["id"] != query_id or value.get("error"):
            raise ValueError("Failed or foreign Trino query result")
        if "data" in value:
            if not isinstance(value["data"], list):
                raise ValueError("Invalid Trino query rows")
            rows.extend(value["data"])
        next_uri = value.get("nextUri")
        if next_uri is None:
            if not isinstance(value.get("stats"), dict) or value["stats"].get("state") != "FINISHED":
                raise ValueError("Trino query is not finished")
            return query_id, rows
        next_url = urllib.parse.urlsplit(next_uri)
        if next_url.scheme != origin.scheme or next_url.netloc != origin.netloc or not next_url.path.startswith("/v1/statement/"):
            raise ValueError("Trino query continuation left its origin")
        if time.monotonic() >= deadline:
            raise RuntimeError("Trino query remains unresolved")
        current, data = next_uri, None
    raise RuntimeError("Trino query exceeded its page limit")


def check(parameters):
    role, coordinator, workers, hostname, port, java, heap, environment = settings(parameters)
    hosts = [(coordinator, True)] + [(worker, False) for worker in workers]
    nodes = []
    for host, is_coordinator in hosts:
        nodes.append(ready_info("http://" + host + ":" + str(port) + "/v1/info", environment, is_coordinator))
    ids = [node["nodeId"] for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("Trino nodes share an identity")
    query_id, rows = statement("http://" + coordinator + ":" + str(port),
                               "SELECT count(*) AS nation_count FROM tpch.tiny.nation")
    if len(rows) != 1 or not isinstance(rows[0], list) or len(rows[0]) != 1 or type(rows[0][0]) is not int or rows[0][0] != 25:
        raise ValueError("Trino TPCH query returned an unexpected result")
    return {"coordinator": coordinator, "workers": workers, "nodes": nodes,
            "query_id": query_id, "nation_count": rows[0][0]}


def execute(request):
    parameters, action = request["parameters"], request["action"]
    role, coordinator, workers, hostname, port, java, heap, environment = settings(parameters)
    if action == "install":
        return {"software": install_archive("trino", VERSION, parameters.get("binary_url") or URL,
                SHA512, "trino-server-483", REQUIRED, maximum_archive=1024 ** 3)}
    if action == "version":
        return {"software": installed()}
    if action == "configure":
        return {"configuration": configure(parameters)}
    if action == "check":
        return {"query": check(parameters)}
    if role not in {"coordinator", "worker"} or action not in {"start", "stop", "status"}:
        raise ValueError("Unsupported Trino action")
    observed = unit_observation("ambari-trino.service", None if action == "status" else action)
    if action == "status" and observed["active_state"] != "active":
        raise RuntimeError("Trino component is not active")
    return {"systemd": observed}


if __name__ == "__main__":
    main(execute)
