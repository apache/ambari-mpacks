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
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from observations import atomic_json, unit_observation, validate_request

IDENTITY = ("schema_version", "definition_snapshot", "execution_id", "task_id", "action")


def resolve_topology(service, parameters, topology):
    value = dict(parameters)
    fields = {"airflow": {"server_host": ("airflow_server_hosts", True)},
              "celeborn": {"master_host": ("celeborn_master_hosts", True),
                           "worker_hosts": ("celeborn_worker_hosts", False)}}[service]
    for field, (key, single) in fields.items():
        if value.get(field):
            continue
        hosts = topology.get(key)
        if not isinstance(hosts, (list, tuple)) or not hosts or (single and len(hosts) != 1):
            raise ValueError("Missing or ambiguous component assignment: " + key)
        hosts = sorted(set(host_value(host) for host in hosts))
        value[field] = hosts[0] if single else ",".join(hosts)
    return value


def result(request, outcome, observed):
    # Configuration can contain credentials; never publish the request parameters.
    return dict({key: request[key] for key in IDENTITY}, outcome=outcome, observations=observed)


def validate_result(request, value):
    if not isinstance(value, dict):
        raise ValueError("Missing structured result")
    for key in IDENTITY:
        if type(value.get(key)) is not type(request[key]) or value.get(key) != request[key]:
            raise ValueError("Missing or foreign execution identity")
    if value.get("outcome") not in {"APPLIED", "UNRESOLVED"} or not isinstance(value.get("observations"), dict) or not value["observations"]:
        raise ValueError("Invalid observation contract")
    return value


def path_value(value, roots=("/var/lib/", "/opt/", "/usr/lib/jvm/")):
    if (not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
            or ".." in Path(value).parts or not any(value.startswith(root) for root in roots)):
        raise ValueError("Invalid managed runtime path")
    return Path(value)


def host_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", value):
        raise ValueError("An explicit service hostname is required")
    return value


def port_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", value) or int(value) > 65535:
        raise ValueError("Invalid service port")
    return int(value)


def no_links(path):
    for parent in (path,) + tuple(path.parents):
        if parent.is_symlink():
            raise ValueError("Managed paths must not traverse symbolic links")


def directory(path, user, mode=0o750):
    path = Path(path)
    no_links(path)
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    account = pwd.getpwnam(user)
    os.chown(str(path), account.pw_uid, account.pw_gid)
    os.chmod(str(path), mode)
    return path


def owned_file(path, content, user="root", mode=0o640):
    path = Path(path)
    no_links(path)
    account = pwd.getpwnam(user)
    descriptor, temporary = tempfile.mkstemp(prefix=".ambari-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), account.pw_uid, account.pw_gid)
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(command, timeout=600, env=None):
    completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=timeout, env=env, check=False)
    if completed.returncode:
        raise RuntimeError("Runtime command failed; inspect the service journal")
    return completed


def reload_units():
    import dbus
    bus = dbus.SystemBus()
    try:
        manager = dbus.Interface(bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1"),
                                 "org.freedesktop.systemd1.Manager")
        manager.Reload()
    finally:
        bus.close()


def unit(name, user, executable, environment, working_directory, arguments=""):
    for value in (name, user):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError("Invalid systemd identity")
    lines = ["[Unit]", "Description=Ambari managed " + name, "After=network-online.target",
             "[Service]", "Type=simple", "User=" + user, "Group=" + user,
             "WorkingDirectory=" + str(working_directory)]
    for key, value in sorted(environment.items()):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or any(c in str(value) for c in '\r\n\x00"\\%'):
            raise ValueError("Invalid systemd environment")
        lines.append('Environment="' + key + '=' + str(value) + '"')
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(executable)) or any(c in arguments for c in '\r\n\x00"%'):
        raise ValueError("Invalid service command")
    lines.extend(["ExecStart=" + str(executable) + (" " + arguments if arguments else ""),
                  "Restart=no", "TimeoutStopSec=90", "KillMode=control-group",
                  "SuccessExitStatus=143", "UMask=0027", ""])
    owned_file(Path("/etc/systemd/system") / name, "\n".join(lines))


def json_http(url, data=None, headers=None):
    request = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                     headers=dict({"Accept": "application/json", "Content-Type": "application/json"}, **(headers or {})))
    # Do not send credentials or observe an unexpected endpoint via a redirect.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        payload = response.read(1024 * 1024 + 1)
        if response.status not in {200, 201} or len(payload) > 1024 * 1024:
            raise ValueError("Invalid bounded API response")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Expected an API object")
    return value


def download(url, target, expected, algorithm="sha512", maximum=1024 * 1024 * 1024):
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Software downloads require HTTPS")
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Download URL must not contain credentials or fragments")
    digest = hashlib.new(algorithm)
    count = 0
    with urllib.request.urlopen(url, timeout=60) as response, Path(target).open("xb") as stream:
        if urllib.parse.urlsplit(response.url).scheme != "https":
            raise ValueError("Download redirected outside HTTPS")
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            count += len(block)
            if count > maximum:
                raise ValueError("Software download exceeds its limit")
            stream.write(block)
            digest.update(block)
        stream.flush()
        os.fsync(stream.fileno())
    if digest.hexdigest() != expected:
        raise ValueError("Software download differs from its pinned digest")


def main(execute):
    import sys
    request = validate_request(json.loads(Path(sys.argv[1]).read_text()))
    try:
        observed = execute(request)
        value = result(request, "APPLIED", observed)
    except Exception as error:
        from native_config import ConfigurationError
        observation = {"error_type": type(error).__name__}
        if isinstance(error, ConfigurationError):
            observation["configuration_error"] = str(error)
        value = result(request, "UNRESOLVED", observation)
        atomic_json(sys.argv[2], value)
        raise SystemExit(1)
    atomic_json(sys.argv[2], value)
