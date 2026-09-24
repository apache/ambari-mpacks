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
import os
import pwd
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from observations import atomic_json, package_observation, unit_observation, validate_request, validate_result

UNIT = "ambari-kyuubi.service"
CONFIG = Path("/etc/kyuubi/ambari")
DATA = Path("/var/lib/kyuubi")
LOGS = Path("/var/log/kyuubi")


def settings(parameters):
    paths = {}
    for key in ("kyuubi_home", "spark_home", "java_home", "hadoop_conf_dir"):
        value = parameters.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or ".." in Path(value).parts:
            raise ValueError("Invalid Kyuubi runtime path")
        paths[key] = value
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", parameters.get("package_name", "")):
        raise ValueError("An exact Kyuubi RPM name is required")
    host = parameters.get("server_host", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise ValueError("An explicit Kyuubi service-check hostname is required")
    defaults = parameters.get("defaults")
    if not isinstance(defaults, dict):
        raise ValueError("Kyuubi defaults are required")
    for key, value in defaults.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]+", key) or not isinstance(value, str) or any(c in value for c in "\r\n\x00"):
            raise ValueError("Invalid Kyuubi configuration property")
    port = int(defaults.get("kyuubi.frontend.thrift.binary.bind.port", "10009"))
    if not 1 <= port <= 65535 or not defaults.get("kyuubi.ha.addresses"):
        raise ValueError("A valid Kyuubi port and ZooKeeper quorum are required")
    if defaults.get("spark.master") not in {"yarn", "local[2]"}:
        raise ValueError("Only the declared YARN and local validation modes are supported")
    return paths, defaults, host, port


def write_owned(path, content, account):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Managed configuration cannot be a symbolic link")
    descriptor, temporary = tempfile.mkstemp(prefix=".ambari-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o640)
            os.fchown(stream.fileno(), account.pw_uid, account.pw_gid)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
        actual = path.read_bytes()
        if actual != content.encode("utf-8"):
            raise RuntimeError("Managed configuration does not match")
        return {"path": str(path), "sha256": hashlib.sha256(actual).hexdigest()}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure(parameters, client=False):
    paths, defaults, host, port = settings(parameters)
    account = pwd.getpwnam("kyuubi")
    for path in (CONFIG, DATA, LOGS, DATA / "work", DATA / "run"):
        if path.is_symlink():
            raise ValueError("Managed directory cannot be a symbolic link")
        path.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(str(path), account.pw_uid, account.pw_gid)
    fixed = {
        "kyuubi.authentication": "NONE", "kyuubi.engine.type": "SPARK_SQL",
        "kyuubi.frontend.protocols": "THRIFT_BINARY", "kyuubi.engine.doAs.enabled": "false",
        "kyuubi.session.engine.initialize.timeout": "PT3M",
    }
    properties = dict(defaults)
    for key, value in fixed.items():
        if key in properties and properties[key] != value:
            raise ValueError("Unsupported Kyuubi authentication or engine configuration")
        properties[key] = value
    rendered = "".join(key + "=" + value + "\n" for key, value in sorted(properties.items()))
    environment = (
        "export JAVA_HOME=" + paths["java_home"] + "\n"
        "export SPARK_HOME=" + paths["spark_home"] + "\n"
        "export HADOOP_CONF_DIR=" + paths["hadoop_conf_dir"] + "\n"
        "export KYUUBI_LOG_DIR=" + str(LOGS) + "\n"
        "export KYUUBI_PID_DIR=" + str(DATA / "run") + "\n"
        "export KYUUBI_WORK_DIR_ROOT=" + str(DATA / "work") + "\n"
        "export KYUUBI_JAVA_OPTS='-Xmx768m'\n")
    observations = [
        write_owned(CONFIG / "kyuubi-defaults.conf", rendered, account),
        write_owned(CONFIG / "kyuubi-env.sh", environment, account),
    ]
    if not client:
        for binary in (Path(paths["kyuubi_home"]) / "bin/kyuubi",
                       Path(paths["spark_home"]) / "bin/spark-submit",
                       Path(paths["java_home"]) / "bin/java"):
            if not binary.is_file() or not os.access(str(binary), os.X_OK):
                raise RuntimeError("Required runtime executable is missing")
        unit = ("[Unit]\nDescription=Ambari managed Apache Kyuubi\nAfter=network.target\n"
                "[Service]\nType=simple\nUser=kyuubi\nGroup=kyuubi\n"
                "WorkingDirectory=" + str(DATA) + "\n"
                "Environment=KYUUBI_CONF_DIR=" + str(CONFIG) + "\n"
                "ExecStart=" + paths["kyuubi_home"] + "/bin/kyuubi run\n"
                "Restart=no\nTimeoutStopSec=60\nKillMode=control-group\nUMask=0027\n")
        observations.append(write_owned(Path("/etc/systemd/system") / UNIT, unit, pwd.getpwnam("root")))
        import dbus
        bus = dbus.SystemBus()
        try:
            manager = dbus.Interface(bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1"),
                                     "org.freedesktop.systemd1.Manager")
            manager.Reload()
        finally:
            bus.close()
    return {"files": observations, "client_only": client}


def sql_observation(request):
    paths, defaults, host, port = settings(request["parameters"])
    account = pwd.getpwnam("kyuubi")
    with tempfile.TemporaryDirectory(prefix="ambari-kyuubi-jdbc-") as directory:
        os.chown(directory, account.pw_uid, account.pw_gid)
        result = Path(directory) / "result.json"
        java = Path(paths["java_home"]) / "bin/java"
        helper = Path(__file__).with_name("KyuubiSqlCheck.java")
        process = subprocess.run(
            ["/usr/sbin/runuser", "-u", "kyuubi", "--", str(java),
             "-cp", paths["kyuubi_home"] + "/beeline-jars/*", str(helper),
             host, str(port), request["definition_snapshot"], request["execution_id"],
             str(request["task_id"]) if request["task_id"] is not None else "null", str(result)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=420, check=False)
        if not result.is_file() or result.stat().st_size > 65536:
            raise RuntimeError("JDBC check has no bounded result")
        observation = validate_result(request, json.loads(result.read_text(encoding="utf-8")))
        sql = observation["observations"]
        if process.returncode != 0 or sql.get("sum") != 45 or type(sql.get("sum")) is not int or sql.get("rows") != 10 or type(sql.get("rows")) is not int:
            raise RuntimeError("JDBC result values do not match")
        for key in ("session_id", "operation_id"):
            if str(uuid.UUID(sql[key])) != sql[key]:
                raise RuntimeError("JDBC result has no canonical operation identity")
        if not isinstance(sql.get("engine_id"), str) or not sql["engine_id"] or sql.get("execution_id") != request["execution_id"] or sql.get("resources_closed") is not True:
            raise RuntimeError("JDBC result has no matching engine/execution observation")
        return sql


def execute(request):
    parameters = request["parameters"]
    settings(parameters)
    action = request["action"]
    observed = {"software": package_observation(parameters["package_name"])}
    if action in {"configure", "configure_client"}:
        observed["configuration"] = configure(parameters, action == "configure_client")
    elif action in {"start", "stop"}:
        observed["systemd"] = unit_observation(UNIT, action)
    elif action == "health":
        observed["systemd"] = unit_observation(UNIT)
        if observed["systemd"]["active_state"] != "active":
            raise RuntimeError("Kyuubi unit is not active")
    elif action == "sql":
        observed["sql"] = sql_observation(request)
    elif action != "version":
        raise ValueError("Unsupported Kyuubi action")
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
