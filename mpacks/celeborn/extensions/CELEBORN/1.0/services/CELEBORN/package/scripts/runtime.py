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
import shutil
import tarfile
import tempfile
import time
from pathlib import Path

from observations import atomic_json, unit_observation
from managed_runtime import directory, download, host_value, json_http, main, no_links, owned_file, path_value, port_value, reload_units, unit

VERSION = "0.7.0"
SHA512 = "58e9bac129e1e817c3d97d69dbbe30baeddc07ecf7e109bda3acdb8b7a8d55380aec663d7c5862b2b770c8c120b78ffc136dde80e6dfe0d6e0519d0815c4973d"
URL = "https://archive.apache.org/dist/celeborn/celeborn-0.7.0/apache-celeborn-0.7.0-bin.tgz"
HOME = Path("/opt/ambari-mpacks/celeborn") / VERSION
CONF = Path("/etc/celeborn/ambari")
DATA = Path("/var/lib/celeborn")
LOGS = Path("/var/log/celeborn")


def settings(parameters):
    role = parameters["component"]
    if role not in {"master", "worker", "check"}:
        raise ValueError("Unknown Celeborn component")
    master = host_value(parameters["master_host"])
    workers = [host_value(host.strip()) for host in parameters["worker_hosts"].split(",")]
    if len(workers) != len(set(workers)):
        raise ValueError("Duplicate worker assignment")
    host = host_value(parameters["hostname"])
    if role == "master" and host != master or role == "worker" and host not in workers:
        raise ValueError("Component placement differs from the configured topology")
    ports = {key: port_value(parameters[key]) for key in (
        "master_port", "master_http_port", "worker_rpc_port", "worker_push_port",
        "worker_fetch_port", "worker_replicate_port", "worker_http_port")}
    if len(set(ports.values())) != len(ports):
        raise ValueError("Component ports must be distinct")
    java = path_value(parameters["java_home"], ("/usr/lib/jvm/",))
    storage = path_value(parameters["storage_directory"], ("/var/lib/celeborn/",))
    for key in ("master_memory", "worker_memory", "worker_direct_memory"):
        if not re.fullmatch(r"[1-9][0-9]*[mg]", parameters[key]):
            raise ValueError("Memory must be an explicit JVM size")
    return role, master, workers, host, ports, java, storage


def extract(archive, target):
    prefix = "apache-celeborn-" + VERSION + "-bin"
    seen = set()
    links = []
    total = 0
    with tarfile.open(str(archive), "r:gz") as source:
        for entry in source:
            parts = Path(entry.name).parts
            if not parts or parts[0] != prefix or ".." in parts or Path(entry.name).is_absolute():
                raise ValueError("Archive leaves its pinned distribution")
            relative = Path(*parts[1:])
            if relative == Path("."):
                if not entry.isdir() or entry.size:
                    raise ValueError("Invalid distribution root")
                continue
            if str(relative) in seen or len(seen) >= 100000:
                raise ValueError("Duplicate or excessive archive entries")
            seen.add(str(relative))
            destination = target / relative
            no_links(destination)
            if entry.isdir() and entry.size == 0:
                destination.mkdir(parents=True, exist_ok=True)
            elif entry.isfile() and not entry.issparse():
                total += entry.size
                if total > 2 * 1024 * 1024 * 1024:
                    raise ValueError("Expanded distribution exceeds its limit")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(entry) as stream, destination.open("xb") as output:
                    shutil.copyfileobj(stream, output)
                destination.chmod(0o755 if entry.mode & 0o111 else 0o644)
            elif entry.issym() and entry.size == 0:
                links.append((destination, entry.linkname))
            else:
                raise ValueError("Unsupported distribution member")
    for destination, link in links:
        if Path(link).is_absolute():
            raise ValueError("Absolute distribution link")
        resolved = (destination.parent / link).resolve()
        resolved.relative_to(target.resolve())
        no_links(destination.parent)
        if resolved.is_symlink() or not resolved.is_file():
            raise ValueError("Distribution link must resolve to an internal file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(link)


def verify_install():
    no_links(HOME)
    receipt = json.loads((HOME / ".ambari-receipt.json").read_text())
    if (type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
            or receipt.get("sha512") != SHA512 or receipt.get("version") != VERSION
            or not isinstance(receipt.get("files"), dict) or not receipt["files"]):
        raise ValueError("Missing verified Celeborn distribution identity")
    for name, expected in receipt["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise ValueError("Invalid installed file identity")
        path = HOME / relative
        no_links(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Installed Celeborn payload differs from its receipt")
    for name, target in receipt.get("links", {}).items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid installed link identity")
        path = HOME / relative
        no_links(path.parent)
        path.resolve().relative_to(HOME.resolve())
        if not path.is_symlink() or os.readlink(str(path)) != target:
            raise ValueError("Installed Celeborn link differs from its receipt")
    return {"version": VERSION, "archive_sha512": SHA512, "verified_files": len(receipt["files"])}


def install(parameters):
    if HOME.exists():
        return verify_install()
    directory(HOME.parent, "root", 0o755)
    cache = directory(Path("/var/cache/ambari-mpacks"), "root", 0o755) / ("celeborn-" + VERSION + ".tgz")
    no_links(cache)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=str(HOME.parent)) as work:
        archive = Path(work) / "binary.tgz"
        if cache.exists():
            digest = hashlib.sha512()
            with cache.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != SHA512:
                raise ValueError("Cached distribution differs from the pinned archive")
            archive = cache
        else:
            download(parameters.get("binary_url") or URL, archive, SHA512)
        target = Path(work) / "distribution"
        target.mkdir(mode=0o755)
        extract(archive, target)
        for required in ("sbin/start-master.sh", "sbin/start-worker.sh", "bin/celeborn-class"):
            if not (target / required).is_file():
                raise ValueError("Incomplete Celeborn distribution")
        hashes = {str(path.relative_to(target)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in target.rglob("*") if path.is_file() and not path.is_symlink()}
        links = {str(path.relative_to(target)): os.readlink(str(path)) for path in target.rglob("*") if path.is_symlink()}
        atomic_json(target / ".ambari-receipt.json",
                    {"schema_version": 1, "version": VERSION, "sha512": SHA512, "files": hashes, "links": links})
        os.rename(str(target), str(HOME))
    return verify_install()


def configure(parameters):
    from native_config import LOG4J_DEFAULT, content, environment as native_environment, properties, render_properties
    role, master, workers, host, ports, java, storage = settings(parameters)
    if role == "check":
        raise ValueError("A check cannot configure components")
    for path in (CONF, DATA, LOGS, DATA / "run", storage):
        directory(path, "celeborn")
    values = {
        "celeborn.master.host": master, "celeborn.master.port": ports["master_port"],
        "celeborn.master.endpoints": master + ":" + str(ports["master_port"]),
        "celeborn.master.ha.enabled": "false", "celeborn.master.http.host": "0.0.0.0",
        "celeborn.master.http.port": ports["master_http_port"], "celeborn.worker.http.host": "0.0.0.0",
        "celeborn.worker.http.port": ports["worker_http_port"],
        "celeborn.worker.rpc.port": ports["worker_rpc_port"], "celeborn.worker.push.port": ports["worker_push_port"],
        "celeborn.worker.fetch.port": ports["worker_fetch_port"], "celeborn.worker.replicate.port": ports["worker_replicate_port"],
        "celeborn.worker.storage.dirs": str(storage), "celeborn.storage.availableTypes": "HDD",
        "celeborn.metrics.enabled": "true",
    }
    defaults = {key: values.pop(key) for key in ("celeborn.storage.availableTypes", "celeborn.metrics.enabled")}
    values = properties(parameters, "celeborn-defaults", values, defaults)
    owned_file(CONF / "celeborn-defaults.conf", render_properties(values), "celeborn")
    owned_file(CONF / "log4j2.properties", content(parameters, "celeborn-log4j2", LOG4J_DEFAULT), "celeborn")
    environment = {"JAVA_HOME": str(java), "CELEBORN_HOME": str(HOME), "CELEBORN_CONF_DIR": str(CONF),
        "CELEBORN_LOG_DIR": str(LOGS), "CELEBORN_PID_DIR": str(DATA / "run"), "CELEBORN_NO_DAEMONIZE": "1",
        "CELEBORN_LOCAL_HOSTNAME": host, "CELEBORN_MASTER_MEMORY": parameters["master_memory"],
        "CELEBORN_WORKER_MEMORY": parameters["worker_memory"],
        "CELEBORN_WORKER_OFFHEAP_MEMORY": parameters["worker_direct_memory"]}
    extra_environment = native_environment(parameters, "celeborn-environment", environment)
    from native_config import shell_exports
    owned_file(CONF / "celeborn-env.sh", shell_exports(extra_environment), "celeborn")
    unit("ambari-celeborn-" + role + ".service", "celeborn", HOME / ("sbin/start-" + role + ".sh"),
         environment, DATA)
    reload_units()
    return {"component": role, "master": master, "worker_hosts": workers, "storage_directory": str(storage)}


def validate_worker(value, host, ports):
    if not isinstance(value, dict) or value.get("host") != host:
        raise ValueError("Foreign worker response")
    for field, config in (("rpcPort", "worker_rpc_port"), ("pushPort", "worker_push_port"),
                           ("fetchPort", "worker_fetch_port"), ("replicatePort", "worker_replicate_port")):
        if type(value.get(field)) is not int or value[field] != ports[config]:
            raise ValueError("Worker endpoint identity differs from the configured component")
    if value.get("isRegistered") is not True or value.get("isShutdown") is not False:
        raise ValueError("Worker is not registered and active")
    return {key: value[key] for key in ("host", "rpcPort", "pushPort", "fetchPort", "replicatePort", "isRegistered", "isShutdown")}


def check(parameters):
    role, master, workers, host, ports, java, storage = settings(parameters)
    master_url = "http://" + master + ":" + str(ports["master_http_port"])
    inventory = json_http(master_url + "/api/v1/workers")
    registered = inventory.get("workers")
    if not isinstance(registered, list):
        raise ValueError("Missing typed master worker inventory")
    observations = []
    for worker in workers:
        observed = validate_worker(json_http("http://" + worker + ":" + str(ports["worker_http_port"]) + "/api/v1/workers"),
                                   worker, ports)
        matching = [item for item in registered if item.get("host") == worker and item.get("rpcPort") == ports["worker_rpc_port"]]
        if len(matching) != 1:
            raise ValueError("Worker is missing or ambiguous at the selected master")
        observations.append(observed)
    return {"master": master, "master_http_port": ports["master_http_port"], "workers": observations}


def execute(request):
    parameters, action = request["parameters"], request["action"]
    role, master, workers, host, ports, java, storage = settings(parameters)
    if action == "install":
        return {"software": install(parameters)}
    if action == "version":
        return {"software": verify_install()}
    if action == "configure":
        verify_install()
        return {"configuration": configure(parameters)}
    if action == "check":
        return {"cluster": check(parameters)}
    if role not in {"master", "worker"} or action not in {"start", "stop", "status"}:
        raise ValueError("Unsupported Celeborn action")
    observed = unit_observation("ambari-celeborn-" + role + ".service", None if action == "status" else action)
    if action == "status" and observed["active_state"] != "active":
        raise RuntimeError("Celeborn component is not active")
    return {"systemd": observed}


if __name__ == "__main__":
    main(execute)
