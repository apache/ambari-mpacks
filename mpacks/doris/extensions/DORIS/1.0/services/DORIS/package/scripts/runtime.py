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

import hashlib
import json
import re
import socket
import time
from decimal import Decimal
from pathlib import Path

from managed_runtime import directory, host_value, no_links, owned_file, path_value, port_value, reload_units, result, unit
from observations import atomic_json, unit_observation, validate_request
from verified_archive import install_archive, verify_install

VERSION = "4.1.4"
SHA512 = "15ba9dbb76b60b54360cd8580e3433cad0fa85e216512da72afc3559eff2eac708dc839f1634e2415d4b54a3abe0722d98471205b9fd52e12380d823ee144dbc"
URL = "https://apache-doris-releases.oss-accelerate.aliyuncs.com/apache-doris-4.1.4-bin-arm64.tar.gz"
REQUIRED = ["fe/bin/start_fe.sh", "fe/lib/doris-fe.jar", "fe/conf/fe.conf",
            "be/bin/start_be.sh", "be/lib/doris_be", "be/conf/be.conf"]
HOME = Path("/opt/ambari-mpacks/doris/4.1.4")
DATA = Path("/var/lib/doris")


class CheckFailure(Exception):
    def __init__(self, stage, database="", cleanup=True):
        self.observation = {"stage": stage, "database": database, "cleanup": cleanup}


def settings(parameters):
    role = parameters["component"]
    if role not in {"fe", "be", "check"}:
        raise ValueError("Unknown Doris component")
    fe, be = host_value(parameters["fe_host"]), host_value(parameters["be_host"])
    host = host_value(parameters["hostname"])
    if role == "fe" and host != fe or role == "be" and host != be:
        raise ValueError("Doris component placement differs from the assigned host")
    ports = {key: port_value(parameters[key]) for key in (
        "fe_http_port", "fe_rpc_port", "fe_query_port", "fe_edit_log_port",
        "be_port", "be_http_port", "be_heartbeat_port", "be_brpc_port")}
    if fe == be and len(set(ports.values())) != len(ports):
        raise ValueError("Co-located Doris component ports must be distinct")
    java = path_value(parameters["java_home"], ("/usr/lib/jvm/",))
    java = path_value(str(java.resolve()), ("/usr/lib/jvm/",))
    no_links(java)
    release = java / "release"
    if not release.is_file() or not (java / "bin/java").is_file() or not re.search(
            r'^JAVA_VERSION="17\.[0-9.]+"$', release.read_text(), re.MULTILINE):
        raise ValueError("Doris 4.1.4 requires Java 17")
    heap = parameters["fe_heap_size"]
    if not isinstance(heap, str) or not re.fullmatch(r"[2-9][0-9]*[gG]", heap):
        raise ValueError("Doris FE heap must be at least 2G")
    be_memory = parameters["be_memory_limit"]
    if not isinstance(be_memory, str) or not re.fullmatch(r"[2-9][0-9]*[gG]", be_memory):
        raise ValueError("Doris BE memory limit must be at least 2G")
    password = parameters["root_password"]
    if not isinstance(password, str) or not 12 <= len(password) <= 128 or "\x00" in password:
        raise ValueError("An explicit Doris root password is required")
    return role, fe, be, host, ports, java, heap.upper(), be_memory.upper(), password


def installed():
    return verify_install(HOME, "doris", VERSION, SHA512, REQUIRED)


def install(parameters):
    settings(parameters)
    return install_archive("doris", VERSION, parameters.get("binary_url") or URL,
            SHA512, "apache-doris-4.1.4-bin-arm64", REQUIRED,
            maximum_archive=5 * 1024 ** 3, maximum_expanded=16 * 1024 ** 3)


def _linked(destination, source):
    if destination.is_symlink():
        if destination.resolve() != source.resolve():
            raise ValueError("Doris runtime resource differs from its pinned archive")
    elif destination.exists():
        raise ValueError("Unowned Doris runtime resource exists")
    else:
        destination.symlink_to(source)


def configure(parameters):
    from native_config import properties
    role, fe, be, host, ports, java, heap, be_memory, password = settings(parameters)
    if role == "check":
        raise ValueError("A service check cannot configure Doris")
    installed()
    for path in (DATA, DATA / role, DATA / role / "bin", DATA / role / "conf",
                 DATA / role / "log", DATA / "fe/meta", DATA / "be/storage"):
        directory(path, "doris")
    stage = DATA / role
    source = HOME / role
    script_name = "start_" + role + ".sh"
    script = stage / "bin" / script_name
    owned_file(script, (source / "bin" / script_name).read_text(), "doris", 0o750)
    for item in source.iterdir():
        if item.name in {"bin", "conf", "log", "storage", "meta", "doris-meta"}:
            continue
        _linked(stage / item.name, item)
    for item in (source / "conf").rglob("*"):
        relative = item.relative_to(source / "conf")
        if str(relative) in {"fe.conf", "be.conf"}:
            continue
        if item.is_symlink():
            raise ValueError("Unexpected Doris configuration resource")
        target = stage / "conf" / relative
        if item.is_dir():
            directory(target, "doris")
        elif item.is_file():
            owned_file(target, item.read_text(), "doris")
        else:
            raise ValueError("Unexpected Doris configuration resource")
    if role == "fe":
        values = {"JAVA_HOME": str(java), "JAVA_OPTS": "-Xmx" + heap,
                  "LOG_DIR": str(stage / "log"), "meta_dir": str(DATA / "fe/meta"),
                  "http_port": ports["fe_http_port"], "rpc_port": ports["fe_rpc_port"],
                  "query_port": ports["fe_query_port"], "edit_log_port": ports["fe_edit_log_port"]}
        marker = DATA / "fe/identity.json"
        no_links(marker)
        identity = {"schema_version": 1, "version": VERSION, "fe_host": fe,
                    "root_password_sha256": hashlib.sha256(password.encode()).hexdigest()}
        if marker.exists():
            if any(json.loads(marker.read_text()).get(key) != value for key, value in identity.items()):
                raise ValueError("Doris FE identity differs from its retained metadata")
        elif any((DATA / "fe/meta").iterdir()):
            raise ValueError("Unowned Doris FE metadata exists")
        else:
            atomic_json(marker, dict(identity, phase="PENDING"))
    else:
        values = {"JAVA_HOME": str(java), "LOG_DIR": str(stage / "log"),
                  "storage_root_path": str(DATA / "be/storage"), "mem_limit": be_memory,
                  "be_port": ports["be_port"], "webserver_port": ports["be_http_port"],
                  "heartbeat_service_port": ports["be_heartbeat_port"], "brpc_port": ports["be_brpc_port"]}
    config = source / "conf" / (role + ".conf")
    values = properties(parameters, "doris-" + role, values)
    # Remove replaced keys, preserving upstream comments and version-specific JVM defaults.
    lines = "\n".join(line for line in config.read_text().splitlines()
                      if line.split("=", 1)[0].strip() not in values)
    if hasattr(values, "source"):
        lines += "\n" + values.source.rstrip() + "\n"
        lines += "".join(key + " = " + str(value) + "\n" for key, value in values.items() if key not in values.explicit)
    else:
        lines += "\n" + "".join(key + " = " + str(value) + "\n" for key, value in values.items())
    owned_file(stage / "conf" / (role + ".conf"), lines, "doris")
    unit("ambari-doris-" + role + ".service", "doris", Path("/bin/bash"),
         {"JAVA_HOME": str(java)}, stage, str(script))
    reload_units()
    return {"role": role, "host": host, "metadata": str(DATA / "fe/meta"),
            "storage": str(DATA / "be/storage")}


def connection(host, port, password):
    import pymysql
    return pymysql.connect(host=host, port=port, user="root", password=password,
                           connect_timeout=10, read_timeout=20, write_timeout=20, autocommit=True)


def query(connection, sql, parameters=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()] if columns else []
    return rows


def _addresses(host):
    values = {host}
    values.update(row[4][0] for row in socket.getaddrinfo(host, None, family=socket.AF_INET))
    return values


def validate_nodes(frontends, backends, fe, be, ports):
    if len(frontends) != 1 or len(backends) != 1:
        raise ValueError("Doris FE/BE inventory is missing or ambiguous")
    frontend, backend = frontends[0], backends[0]
    if (frontend.get("Host") not in _addresses(fe) or frontend.get("Alive") not in (True, "true")
            or frontend.get("IsMaster") not in (True, "true")
            or str(frontend.get("EditLogPort")) != str(ports["fe_edit_log_port"])):
        raise ValueError("Doris FE identity or readiness differs")
    if (backend.get("Host") not in _addresses(be) or backend.get("Alive") not in (True, "true")
            or str(backend.get("HeartbeatPort")) != str(ports["be_heartbeat_port"])
            or str(backend.get("HttpPort")) != str(ports["be_http_port"])):
        raise ValueError("Doris BE identity or readiness differs")
    return {"fe": frontend["Host"], "be": backend["Host"],
            "be_heartbeat_port": ports["be_heartbeat_port"]}


def bootstrap_fe(parameters):
    import pymysql
    role, fe, be, host, ports, java, heap, be_memory, password = settings(parameters)
    marker = DATA / "fe/identity.json"
    if not marker.is_file():
        raise ValueError("Doris FE has no owned initialization marker")
    identity = json.loads(marker.read_text())
    expected = {"schema_version": 1, "version": VERSION, "fe_host": fe,
                "root_password_sha256": hashlib.sha256(password.encode()).hexdigest()}
    if any(identity.get(key) != value for key, value in expected.items()) or identity.get("phase") not in {"PENDING", "COMPLETE"}:
        raise ValueError("Invalid Doris FE initialization phase")
    deadline = time.monotonic() + 180
    while True:
        try:
            authenticated = connection(fe, ports["fe_query_port"], password)
            authenticated.close()
            atomic_json(marker, dict(identity, phase="COMPLETE"))
            return {"administrator": "root", "phase": "COMPLETE"}
        except pymysql.err.OperationalError as error:
            code = error.args[0] if error.args and type(error.args[0]) is int else None
            if code == 1045 and identity["phase"] == "PENDING":
                break
            if code not in {2003, 2006}:
                raise
            if time.monotonic() >= deadline:
                break
            time.sleep(3)
    if identity["phase"] == "COMPLETE":
        raise RuntimeError("Retained Doris root credential no longer authenticates")
    unauthenticated = connection(fe, ports["fe_query_port"], "")
    try:
        with unauthenticated.cursor() as cursor:
            cursor.execute("SET PASSWORD FOR 'root' = PASSWORD(%s)", (password,))
    finally:
        unauthenticated.close()
    authenticated = connection(fe, ports["fe_query_port"], password)
    authenticated.close()
    atomic_json(marker, dict(identity, phase="COMPLETE"))
    return {"administrator": "root", "phase": "COMPLETE"}


def register_be(parameters):
    role, fe, be, host, ports, java, heap, be_memory, password = settings(parameters)
    client = connection(fe, ports["fe_query_port"], password)
    try:
        backends = query(client, "SHOW BACKENDS")
        if not backends:
            endpoint = be + ":" + str(ports["be_heartbeat_port"])
            query(client, 'ALTER SYSTEM ADD BACKEND "' + endpoint + '"')
        elif len(backends) != 1 or backends[0].get("Host") not in _addresses(be) or str(
                backends[0].get("HeartbeatPort")) != str(ports["be_heartbeat_port"]):
            raise ValueError("Existing Doris BE assignment differs from the selected host")
        deadline = time.monotonic() + 180
        while True:
            observed = query(client, "SHOW BACKENDS")
            if len(observed) == 1 and observed[0].get("Host") in _addresses(be) and observed[0].get("Alive") in (True, "true"):
                return {"host": observed[0]["Host"], "heartbeat_port": ports["be_heartbeat_port"],
                        "alive": True}
            if time.monotonic() >= deadline:
                raise RuntimeError("Doris BE registration remains unresolved")
            time.sleep(3)
    finally:
        client.close()


def check(request):
    role, fe, be, host, ports, java, heap, be_memory, password = settings(request["parameters"])
    client = connection(fe, ports["fe_query_port"], password)
    name = "ambari_mpack_" + request["execution_id"].replace("-", "")
    stage, created, cleanup, failure = "inventory", False, True, False
    try:
        frontends = query(client, "SHOW FRONTENDS")
        backends = query(client, "SHOW BACKENDS")
        nodes = validate_nodes(frontends, backends, fe, be, ports)
        stage = "create"
        query(client, "CREATE DATABASE " + name)
        created = True
        query(client, "CREATE TABLE " + name + ".probe (id INT, value INT) ENGINE=OLAP DUPLICATE KEY(id) "
              'DISTRIBUTED BY HASH(id) BUCKETS 1 PROPERTIES ("replication_num"="1")')
        stage = "write"
        query(client, "INSERT INTO " + name + ".probe VALUES (1, 42)")
        stage = "read"
        rows = query(client, "SELECT COUNT(*) AS row_count, SUM(value) AS value_sum FROM " + name + ".probe")
        if (len(rows) != 1 or type(rows[0].get("row_count")) is not int or rows[0]["row_count"] != 1
                or type(rows[0].get("value_sum")) not in (int, Decimal)
                or rows[0]["value_sum"] != 42):
            raise ValueError("Doris operation-owned table result differs")
    except Exception:
        failure = True
    finally:
        if created:
            try:
                query(client, "DROP DATABASE " + name)
                listed = query(client, "SHOW DATABASES")
                cleanup = not any(name in row.values() for row in listed)
            except Exception:
                cleanup = False
        client.close()
    if failure or not cleanup:
        raise CheckFailure(stage if cleanup else "cleanup", name, cleanup)
    return {"database": name, "row_count": 1, "value_sum": 42, "nodes": nodes, "cleanup": True}


def execute(request):
    parameters, action = request["parameters"], request["action"]
    role, fe, be, host, ports, java, heap, be_memory, password = settings(parameters)
    if action == "install":
        return {"software": install(parameters)}
    if action == "version":
        return {"software": installed()}
    if action == "configure":
        return {"configuration": configure(parameters)}
    if action == "check":
        return {"query": check(request)}
    if role not in {"fe", "be"} or action not in {"start", "stop", "status"}:
        raise ValueError("Unsupported Doris action")
    observed = unit_observation("ambari-doris-" + role + ".service", None if action == "status" else action)
    if action == "status" and observed["active_state"] != "active":
        raise RuntimeError("Doris component is not active")
    if action == "status" and role == "fe":
        marker = DATA / "fe/identity.json"
        no_links(marker)
        identity = json.loads(marker.read_text()) if marker.is_file() else {}
        if (identity.get("phase") != "COMPLETE" or identity.get("fe_host") != fe
                or identity.get("root_password_sha256") != hashlib.sha256(password.encode()).hexdigest()):
            raise RuntimeError("Doris FE initialization is unresolved")
    if action == "start":
        return {"systemd": observed, "registration": bootstrap_fe(parameters) if role == "fe" else register_be(parameters)}
    return {"systemd": observed}


def main():
    import sys
    request = validate_request(json.loads(Path(sys.argv[1]).read_text()))
    try:
        value = result(request, "APPLIED", execute(request))
    except CheckFailure as error:
        value = result(request, "UNRESOLVED", error.observation)
        atomic_json(sys.argv[2], value)
        raise SystemExit(1)
    except Exception as error:
        value = result(request, "UNRESOLVED", {"error_type": type(error).__name__})
        atomic_json(sys.argv[2], value)
        raise SystemExit(1)
    atomic_json(sys.argv[2], value)


if __name__ == "__main__":
    main()
