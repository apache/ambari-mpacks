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
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from managed_runtime import directory, host_value, main, no_links, owned_file, path_value, port_value, reload_units, unit
from observations import atomic_json, unit_observation
from verified_archive import install_archive, verify_install

VERSION = "3.1.9"
SHA512 = "b09e7a11245dc9db8be8c0600857f077c4287380a676577bf3157e98ef2940ab5164d954e30596503dd0a52ab5866d5a7cd4edc88b2f04bdc3407ca441fbd764"
URL = "https://archive.apache.org/dist/dolphinscheduler/3.1.9/apache-dolphinscheduler-3.1.9-bin.tar.gz"
ROLES = ("master-server", "worker-server", "api-server", "alert-server")
REQUIRED = [role + "/bin/start.sh" for role in ROLES] + [
    "tools/bin/upgrade-schema.sh", "bin/env/dolphinscheduler_env.sh"]
HOME = Path("/opt/ambari-mpacks/dolphinscheduler/3.1.9")
CONF = Path("/etc/dolphinscheduler/ambari")
DATA = Path("/var/lib/dolphinscheduler")
DEFAULT_ADMIN_HASH = "7ad2410b2f4c074479a8937a28a22b8f"


def settings(parameters):
    role = parameters["component"]
    if role not in {"server", "check"}:
        raise ValueError("Unknown DolphinScheduler component")
    host = host_value(parameters["server_host"])
    assigned = host_value(parameters["hostname"])
    if role == "server" and host != assigned:
        raise ValueError("DolphinScheduler placement differs from the assigned host")
    db_host = host_value(parameters["database_host"])
    zk_host = host_value(parameters["zookeeper_host"])
    db_port = port_value(parameters["database_port"])
    zk_port = port_value(parameters["zookeeper_port"])
    api_port = port_value(parameters["api_port"])
    name, user = parameters["database_name"], parameters["database_user"]
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name):
        raise ValueError("Invalid dedicated DolphinScheduler database")
    if not isinstance(user, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", user):
        raise ValueError("Invalid DolphinScheduler database user")
    password, admin = parameters["database_password"], parameters["admin_password"]
    if not isinstance(password, str) or len(password) < 12 or "\x00" in password:
        raise ValueError("An explicit database password is required")
    if not isinstance(admin, str) or not 12 <= len(admin) <= 20 or "\x00" in admin:
        raise ValueError("DolphinScheduler 3.1.9 requires an explicit 12-20 character administrator password")
    java = path_value(parameters["java_home"], ("/usr/lib/jvm/",))
    java = path_value(str(java.resolve()), ("/usr/lib/jvm/",))
    no_links(java)
    release = java / "release"
    if not release.is_file() or not (java / "bin/java").is_file():
        raise ValueError("A supported Java runtime is required")
    versions = re.findall(r'^JAVA_VERSION="(11|17)\.[0-9.]+"$', release.read_text(), re.MULTILINE)
    if len(versions) != 1:
        raise ValueError("This DolphinScheduler package supports Java 11 or 17")
    return role, host, db_host, db_port, name, user, password, zk_host, zk_port, api_port, admin, java


def installed():
    return verify_install(HOME, "dolphinscheduler", VERSION, SHA512, REQUIRED)


def database(parameters):
    import psycopg2
    role, host, db_host, db_port, name, user, password, zk_host, zk_port, api_port, admin, java = settings(parameters)
    return psycopg2.connect(host=db_host, port=db_port, dbname=name, user=user,
                            password=password, connect_timeout=10)


def schema(parameters):
    role, host, db_host, db_port, name, user, password, zk_host, zk_port, api_port, admin, java = settings(parameters)
    identity = {"schema_version": 1, "database_host": db_host, "database_name": name, "version": VERSION}
    marker = DATA / "database-init.json"
    no_links(marker)
    connection = database(parameters)
    try:
        if not 140000 <= connection.server_version < 190000:
            raise ValueError("DolphinScheduler requires PostgreSQL 14-18")
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(3171909)")
            if cursor.fetchone()[0] is not True:
                raise RuntimeError("DolphinScheduler database initialization is already active")
            cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = current_schema()")
            empty = cursor.fetchone()[0] == 0
        if empty:
            if marker.exists() and json.loads(marker.read_text()) != dict(identity, phase="PENDING"):
                raise ValueError("Existing initialization marker belongs to another database")
            if not marker.exists():
                atomic_json(marker, dict(identity, phase="PENDING"))
            environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
            environment.update(JAVA_HOME=str(java), DATABASE="postgresql", SPRING_PROFILES_ACTIVE="postgresql",
                SPRING_DATASOURCE_URL="jdbc:postgresql://" + db_host + ":" + str(db_port) + "/" + name,
                SPRING_DATASOURCE_USERNAME=user, SPRING_DATASOURCE_PASSWORD=password,
                JAVA_OPTS="-server -Duser.timezone=UTC -Xms256m -Xmx1g")
            process = subprocess.run(["/usr/sbin/runuser", "-m", "-u", "dolphinscheduler", "--", "/bin/bash",
                str(HOME / "tools/bin/upgrade-schema.sh")], cwd=str(DATA), env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800, check=False)
            if process.returncode != 0:
                raise RuntimeError("DolphinScheduler schema initialization failed")
        elif not marker.exists() or any(json.loads(marker.read_text()).get(key) != value
                                        for key, value in identity.items()):
            raise ValueError("Nonempty database has no matching owned initialization marker")
        with connection.cursor() as cursor:
            cursor.execute("SELECT version FROM t_ds_version ORDER BY id DESC LIMIT 1")
            version = cursor.fetchone()
            if version != (VERSION,):
                raise ValueError("DolphinScheduler schema version differs from the pinned release")
            cursor.execute("SELECT id, user_password FROM t_ds_user WHERE user_name = %s", ("admin",))
            users = cursor.fetchall()
            if len(users) != 1 or type(users[0][0]) is not int:
                raise ValueError("DolphinScheduler administrator identity is ambiguous")
            desired = hashlib.md5(admin.encode("utf-8")).hexdigest()
            if users[0][1] == DEFAULT_ADMIN_HASH:
                cursor.execute("UPDATE t_ds_user SET user_password = %s WHERE id = %s AND user_password = %s",
                               (desired, users[0][0], DEFAULT_ADMIN_HASH))
                if cursor.rowcount != 1:
                    raise RuntimeError("DolphinScheduler administrator password update was not observed")
            elif users[0][1] != desired:
                raise ValueError("Existing administrator password differs; refusing to reset it")
            cursor.execute("SELECT user_password FROM t_ds_user WHERE id = %s", (users[0][0],))
            if cursor.fetchone() != (desired,):
                raise RuntimeError("DolphinScheduler administrator password was not verified")
        atomic_json(marker, dict(identity, phase="COMPLETE"))
        return {"database": name, "postgresql_major": connection.server_version // 10000,
                "schema_version": VERSION, "administrator_id": users[0][0]}
    finally:
        connection.close()


def install(parameters):
    settings(parameters)
    source = install_archive("dolphinscheduler", VERSION, parameters.get("binary_url") or URL,
            SHA512, "apache-dolphinscheduler-3.1.9-bin", REQUIRED, maximum_archive=1024 ** 3)
    directory(DATA, "dolphinscheduler")
    return {"software": source, "initialization": schema(parameters)}


def configure(parameters):
    from native_config import content, jvm_options, overlay_properties, properties, render_properties, section
    role, host, db_host, db_port, name, user, password, zk_host, zk_port, api_port, admin, java = settings(parameters)
    if role != "server":
        raise ValueError("A service check cannot configure DolphinScheduler")
    rendered = {}
    protected = ("springdatasourceurl", "springdatasourceusername", "springdatasourcepassword",
                 "springprofiles", "registrytype", "registryzookeeperconnectstring", "serverport",
                 "workertenantautocreate")
    for component in ROLES:
        name_type = "dolphinscheduler-" + component[:-7]
        values = properties(parameters, name_type)
        if any(re.sub(r"[^a-z0-9]", "", key.lower()).startswith(protected) for key in values):
            raise ValueError("Database, registry and listener settings belong to basic settings")
        rendered[component] = render_properties(values)
    common = properties(parameters, "dolphinscheduler-common")
    jvm = jvm_options(parameters, "dolphinscheduler-jvm",
                      "-server\n-Duser.timezone=UTC\n-XX:+ExitOnOutOfMemoryError\n")
    heap = section(parameters, "dolphinscheduler-runtime").get("heap_size", "1g")
    if not re.fullmatch(r"[1-9][0-9]*[mgMG]", heap):
        raise ValueError("DolphinScheduler heap requires an explicit JVM size")
    installed()
    for path in (CONF, DATA, DATA / "logs", DATA / "workspace"):
        directory(path, "dolphinscheduler")
    for component in ROLES:
        custom = CONF / component
        config = directory(custom / "conf", "dolphinscheduler")
        source = HOME / component / "conf"
        for item in source.rglob("*"):
            relative = item.relative_to(source)
            destination = config / relative
            if item.is_symlink():
                raise ValueError("Unexpected DolphinScheduler configuration link")
            if item.is_dir():
                directory(destination, "dolphinscheduler")
            elif item.is_file():
                owned_file(destination, item.read_text(), "dolphinscheduler")
            else:
                raise ValueError("Unsupported DolphinScheduler configuration member")
        owned_file(config / "application.properties", rendered[component], "dolphinscheduler", 0o600)
        if (source / "common.properties").is_file():
            owned_file(config / "common.properties", overlay_properties(
                (source / "common.properties").read_text(), common), "dolphinscheduler", 0o600)
        logging_type = "dolphinscheduler-" + component[:-7] + "-logback"
        owned_file(config / "logback-spring.xml", content(parameters, logging_type,
                   (source / "logback-spring.xml").read_text(), xml=True), "dolphinscheduler")
        libraries = custom / "libs"
        expected = HOME / component / "libs"
        if libraries.is_symlink():
            if libraries.resolve() != expected.resolve():
                raise ValueError("DolphinScheduler classpath differs from its pinned archive")
        elif libraries.exists():
            raise ValueError("Unowned DolphinScheduler classpath exists")
        else:
            libraries.symlink_to(expected)
        if component == "api-server":
            interface = custom / "ui"
            expected_ui = HOME / component / "ui"
            if interface.is_symlink():
                if interface.resolve() != expected_ui.resolve():
                    raise ValueError("DolphinScheduler UI differs from its pinned archive")
            elif interface.exists():
                raise ValueError("Unowned DolphinScheduler UI exists")
            else:
                interface.symlink_to(expected_ui)
    runtime = {"home": str(HOME), "java_home": str(java),
        "database_url": "jdbc:postgresql://" + db_host + ":" + str(db_port) + "/" + name,
        "database_user": user, "database_password": password,
        "zookeeper": zk_host + ":" + str(zk_port), "api_port": api_port}
    runtime["java_opts"] = " ".join(["-Xms256m", "-Xmx" + heap] + jvm)
    owned_file(CONF / "runtime.json", json.dumps(runtime, sort_keys=True), "dolphinscheduler", 0o600)
    owned_file(CONF / "launcher.py", Path(__file__).with_name("launcher.py").read_text(),
               "dolphinscheduler", 0o500)
    for component in ROLES:
        unit("ambari-dolphinscheduler-" + component + ".service", "dolphinscheduler",
             Path("/usr/libexec/platform-python"), {"PYTHONDONTWRITEBYTECODE": "1"}, DATA,
             str(CONF / "launcher.py") + " " + component)
    reload_units()
    return {"server": host, "api_port": api_port, "database": name, "zookeeper": zk_host}


def api(url, data=None, session=None):
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if session is not None:
        headers["Cookie"] = "sessionId=" + session
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    payload = None if data is None else urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        body = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(body) > 1024 * 1024:
            raise ValueError("Invalid bounded DolphinScheduler API response")
    value = json.loads(body)
    if not isinstance(value, dict) or type(value.get("code")) is not int or value["code"] != 0:
        raise ValueError("DolphinScheduler API operation did not succeed")
    return value.get("data")


def registry_rows(value, expected):
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("DolphinScheduler registry role is missing or ambiguous")
    host = value[0].get("host")
    addresses = {expected}
    addresses.update(item[4][0] for item in socket.getaddrinfo(expected, None, family=socket.AF_INET))
    if host not in addresses or type(value[0].get("port")) is not int or value[0]["port"] <= 0:
        raise ValueError("DolphinScheduler registry identity differs from the assigned host")
    return {"host": host, "port": value[0]["port"]}


def check(parameters):
    role, host, db_host, db_port, name, user, password, zk_host, zk_port, api_port, admin, java = settings(parameters)
    installed()
    for component in ROLES:
        observed = unit_observation("ambari-dolphinscheduler-" + component + ".service")
        if observed["active_state"] != "active":
            raise RuntimeError("A DolphinScheduler subsystem is not active")
    base = "http://" + host + ":" + str(api_port) + "/dolphinscheduler"
    deadline = time.monotonic() + 120
    while True:
        try:
            login = api(base + "/login", {"userName": "admin", "userPassword": admin})
            if not isinstance(login, dict) or not isinstance(login.get("sessionId"), str) or not login["sessionId"]:
                raise ValueError("DolphinScheduler login has no session identity")
            session = login["sessionId"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", session):
                raise ValueError("DolphinScheduler returned an invalid session identity")
            master_rows = api(base + "/monitor/masters", session=session)
            worker_rows = api(base + "/monitor/workers", session=session)
            if master_rows and worker_rows:
                masters = registry_rows(master_rows, host)
                workers = registry_rows(worker_rows, host)
                return {"api_host": host, "api_port": api_port, "masters": [masters],
                        "workers": [workers], "database": name}
            if master_rows != [] and worker_rows != []:
                raise ValueError("DolphinScheduler registry response is invalid")
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("DolphinScheduler API or registry remains unresolved")
        time.sleep(3)


def execute(request):
    parameters, action = request["parameters"], request["action"]
    role, host, db_host, db_port, name, user, password, zk_host, zk_port, api_port, admin, java = settings(parameters)
    if action == "install":
        return install(parameters)
    if action == "version":
        return {"software": installed()}
    if action == "configure":
        return {"configuration": configure(parameters)}
    if action == "check":
        return {"cluster": check(parameters)}
    if role != "server" or action not in {"start", "stop", "status"}:
        raise ValueError("Unsupported DolphinScheduler action")
    sequence = ROLES if action != "stop" else tuple(reversed(ROLES))
    observations = []
    for component in sequence:
        observed = unit_observation("ambari-dolphinscheduler-" + component + ".service",
                                    None if action == "status" else action)
        if action == "status" and observed["active_state"] != "active":
            raise RuntimeError("DolphinScheduler component is not active")
        observations.append(observed)
    return {"systemd": observations}


if __name__ == "__main__":
    main(execute)
