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

import configparser
import hashlib
import json
import os
import pwd
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

from observations import atomic_json, unit_observation
from managed_runtime import directory, download, host_value, main, no_links, owned_file, port_value, reload_units, result, run, unit, validate_result

VERSION = "3.3.2"
HOME = Path("/opt/ambari-mpacks/airflow") / VERSION
DATA = Path("/var/lib/airflow")
CONF = Path("/etc/airflow/ambari")
LOGS = Path("/var/log/airflow")
CONSTRAINTS_URL = "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.11.txt"
CONSTRAINTS_SHA256 = "f9a3a164211d2dcf3243b803995f538003e6061dbf9954622dabbe7ff606f0f7"
COMMANDS = ("api-server", "scheduler", "dag-processor", "triggerer")


def settings(parameters):
    if parameters["component"] not in {"server", "check"}:
        raise ValueError("Unsupported Airflow component")
    host = host_value(parameters["server_host"])
    if parameters["component"] == "server" and host_value(parameters["hostname"]) != host:
        raise ValueError("Airflow component must be placed on the configured server")
    port = port_value(parameters["api_port"])
    if not re.fullmatch(r"[1-9][0-9]?", parameters["parallelism"]):
        raise ValueError("Parallelism must be between 1 and 99")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", parameters["database_name"]):
        raise ValueError("Invalid dedicated metadata database name")
    if parameters["database_name"] in {"postgres", "template0", "template1"}:
        raise ValueError("Use a dedicated Airflow metadata database")
    host_value(parameters["database_host"])
    port_value(parameters["database_port"])
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", parameters["database_user"]):
        raise ValueError("Invalid metadata database user")
    for key in ("database_password", "admin_password"):
        value = parameters[key]
        if not isinstance(value, str) or len(value) < 12 or any(c in value for c in "\r\n\x00"):
            raise ValueError("Explicit credentials of at least twelve characters are required")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", parameters["admin_username"]):
        raise ValueError("Invalid administrator username")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", parameters["admin_email"]):
        raise ValueError("An administrator email is required")
    return host, port


def environment():
    clean = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    return dict(clean, AIRFLOW_HOME=str(DATA), AIRFLOW_CONFIG=str(CONF / "airflow.cfg"),
                PYTHONDONTWRITEBYTECODE="1")


def application(request, action):
    account = pwd.getpwnam("airflow")
    with tempfile.TemporaryDirectory(prefix="ambari-airflow-probe-") as work:
        os.chown(work, account.pw_uid, account.pw_gid)
        source, destination = Path(work) / "request.json", Path(work) / "result.json"
        value = dict(request, action=action)
        source.write_text(json.dumps(value))
        os.chmod(str(source), 0o600)
        os.chown(str(source), account.pw_uid, account.pw_gid)
        process = subprocess.run(["/usr/sbin/runuser", "-u", "airflow", "--", str(HOME / "bin/python"),
            str(Path(__file__).with_name("application.py")), str(source), str(destination)],
            env=environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=360, check=False)
        if not destination.is_file() or destination.stat().st_size > 1024 * 1024:
            raise RuntimeError("Missing bounded Airflow application observation")
        observed = validate_result(value, json.loads(destination.read_text()))
        if process.returncode != 0 or observed["outcome"] != "APPLIED":
            # Do not relay upstream errors containing a database URL or credentials.
            raise RuntimeError("Airflow application check failed: " + str(observed["observations"].get("error_type", "Unknown")))
        return observed["observations"]


def install(request):
    no_links(HOME)
    directory(HOME.parent, "root", 0o755)
    marker = HOME / ".ambari-installed.json"
    pending = HOME / ".ambari-installing.json"
    identity = {"schema_version": 1, "version": VERSION, "constraints_sha256": CONSTRAINTS_SHA256}
    if HOME.exists() and not marker.is_file() and (not pending.is_file() or json.loads(pending.read_text()) != identity):
        raise ValueError("An unowned Airflow environment exists; reconcile it before installation")
    if not marker.exists():
        if not HOME.exists():
            HOME.mkdir(mode=0o755)
            atomic_json(pending, identity)
        run(["/usr/bin/python3.11", "-m", "venv", str(HOME)], env=environment())
        constraints = HOME / "constraints.txt"
        if constraints.exists():
            if hashlib.sha256(constraints.read_bytes()).hexdigest() != CONSTRAINTS_SHA256:
                raise ValueError("Retained constraints differ from the pinned source")
        else:
            download(CONSTRAINTS_URL, constraints, CONSTRAINTS_SHA256, "sha256", 1024 * 1024)
        run([str(HOME / "bin/python"), "-m", "pip", "install", "--disable-pip-version-check",
             "--constraint", str(constraints), "apache-airflow[postgres,fab]==" + VERSION],
            timeout=1500, env=environment())
        observed = application(request, "version")
        run([str(HOME / "bin/python"), "-m", "pip", "check"], env=environment())
        atomic_json(marker, identity)
        pending.unlink()
        return observed
    receipt = json.loads(marker.read_text())
    if receipt != identity:
        raise ValueError("Airflow environment identity differs from the selected release")
    constraints = HOME / "constraints.txt"
    if hashlib.sha256(constraints.read_bytes()).hexdigest() != CONSTRAINTS_SHA256:
        raise ValueError("Retained constraints differ from the pinned source")
    try:
        run([str(HOME / "bin/python"), "-m", "pip", "check"], env=environment())
    except RuntimeError:
        run([str(HOME / "bin/python"), "-m", "pip", "install", "--disable-pip-version-check",
             "--constraint", str(constraints), "apache-airflow[postgres,fab]==" + VERSION],
            timeout=1500, env=environment())
        run([str(HOME / "bin/python"), "-m", "pip", "check"], env=environment())
    return application(request, "version")


def configure(parameters):
    from native_config import content, section, validate_properties
    host, port = settings(parameters)
    for path in (CONF, DATA, DATA / "dags", LOGS):
        directory(path, "airflow")
    secret_path = CONF / "secrets.json"
    no_links(secret_path)
    if not secret_path.exists():
        import base64
        owned_file(secret_path, json.dumps({"fernet": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
                   "jwt": secrets.token_urlsafe(48), "api": secrets.token_urlsafe(48)}), mode=0o600)
    saved = json.loads(secret_path.read_text())
    if set(saved) != {"fernet", "jwt", "api"} or any(not isinstance(v, str) or len(v) < 32 for v in saved.values()):
        raise ValueError("Invalid retained Airflow secret state")
    from urllib.parse import quote
    url = "postgresql+psycopg2://" + quote(parameters["database_user"], safe="") + ":" + quote(
        parameters["database_password"], safe="") + "@" + parameters["database_host"] + ":" + str(
        port_value(parameters["database_port"])) + "/" + parameters["database_name"]
    config = configparser.ConfigParser(interpolation=None)
    config.read_dict({
        "core": {"executor": "LocalExecutor", "dags_folder": str(DATA / "dags"), "load_examples": "False",
                 "fernet_key": saved["fernet"], "parallelism": parameters["parallelism"],
                 "auth_manager": "airflow.providers.fab.auth_manager.fab_auth_manager.FabAuthManager",
                 "execution_api_server_url": "http://" + host + ":" + str(port) + "/execution/"},
        "database": {"sql_alchemy_conn": url},
        "logging": {"base_log_folder": str(LOGS)},
        "api": {"host": "0.0.0.0", "port": str(port), "workers": "1", "secret_key": saved["api"]},
        "api_auth": {"jwt_secret": saved["jwt"]},
        "fab": {"config_file": str(CONF / "webserver_config.py")},
        "scheduler": {"enable_health_check": "True"},
    })
    overrides = section(parameters, "airflow-settings")
    from content_formats import Document, parse_ini, render_ini
    if "content" in overrides:
        overrides = parse_ini(overrides["content"])
    validate_properties(overrides, "airflow-settings")
    managed = {"core.executor", "core.fernet_key", "core.parallelism", "core.auth_manager",
               "core.execution_api_server_url", "database.sql_alchemy_conn", "api.host", "api.port",
               "api.secret_key", "api_auth.jwt_secret", "fab.config_file"}
    for key, value in overrides.items():
        group, dot, option = key.partition(".")
        if not dot or key != key.lower() or group == "default" or key in managed or option.endswith(("_cmd", "_secret")):
            raise ValueError("Use section.option for Airflow settings; managed identity cannot be overridden")
        if not config.has_section(group):
            config.add_section(group)
        config.set(group, option, value)
    import io
    text = io.StringIO()
    config.write(text)
    output = render_ini(overrides, {group + "." + key: value for group in config.sections()
                                   for key, value in config.items(group)}) if isinstance(overrides, Document) else text.getvalue()
    owned_file(CONF / "airflow.cfg", output, "airflow", 0o600)
    owned_file(CONF / "webserver_config.py",
               content(parameters, "airflow-webserver",
                       "from flask_appbuilder.security.manager import AUTH_DB\nAUTH_TYPE = AUTH_DB\n"), "airflow")
    dag = DATA / "dags/ambari_mpack_health.py"
    content = Path(__file__).with_name("health_dag.py").read_text()
    if dag.exists() and dag.read_text() != content:
        raise ValueError("An existing health DAG differs from the managed definition")
    owned_file(dag, content, "airflow")
    for command in COMMANDS:
        unit("ambari-airflow-" + command + ".service", "airflow", HOME / "bin/airflow",
             {"AIRFLOW_HOME": str(DATA), "AIRFLOW_CONFIG": str(CONF / "airflow.cfg")}, DATA, command)
    reload_units()
    return {"host": host, "api_port": port, "executor": "LocalExecutor", "processes": list(COMMANDS)}


def execute(request):
    parameters, action = request["parameters"], request["action"]
    settings(parameters)
    if action == "install":
        observed = install(request)
        configure(parameters)
        observed["initialization"] = application(request, "initialize_database")
        observed["administrator"] = application(request, "create_admin")["administrator"]
        return observed
    if action == "version":
        return application(request, "version")
    if action == "configure":
        return {"configuration": configure(parameters)}
    if action in {"initialize_database", "create_admin", "check"}:
        return application(request, action)
    if action not in {"start", "stop", "status"}:
        raise ValueError("Unsupported Airflow action")
    if action == "start":
        application(request, "database")
    observations = []
    for command in reversed(COMMANDS) if action == "stop" else COMMANDS:
        value = unit_observation("ambari-airflow-" + command + ".service", None if action == "status" else action)
        if action == "status" and value["active_state"] != "active":
            raise RuntimeError("An Airflow process is not active")
        observations.append(value)
    return {"systemd": observations}


if __name__ == "__main__":
    main(execute)
