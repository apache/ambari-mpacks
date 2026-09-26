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

import json
import os
import time
import tempfile
import shlex
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".result-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def unit_observation(name, action=None):
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1"),
                             "org.freedesktop.systemd1.Manager")
    job_result = {}
    completed = {}
    receiver = bus.add_signal_receiver(
        lambda job_id, job_path, unit, result: completed.update(
            {str(job_path): {"job_id": int(job_id), "unit": str(unit), "result": str(result)}}),
        signal_name="JobRemoved", dbus_interface="org.freedesktop.systemd1.Manager",
        bus_name="org.freedesktop.systemd1",
    )
    try:
        manager.Subscribe()
        if action:
            method = {"start": manager.StartUnit, "stop": manager.StopUnit, "reload": manager.ReloadUnit}[action]
            job_path = str(method(name, "replace"))
            deadline = time.monotonic() + 60
            context = GLib.MainContext.default()
            while job_path not in completed and time.monotonic() < deadline:
                while context.pending():
                    context.iteration(False)
                time.sleep(0.05)
            job_result = completed.get(job_path)
            if not job_result or job_result["unit"] != name or job_result["result"] != "done":
                raise RuntimeError("Systemd job has no matching successful result")
            job_result = dict(job_result, job_path=job_path)
        # Stopped units may already have been garbage-collected by systemd.
        path = manager.LoadUnit(name)
        properties = dbus.Interface(bus.get_object("org.freedesktop.systemd1", path),
                                    "org.freedesktop.DBus.Properties")
        observation = properties.GetAll("org.freedesktop.systemd1.Unit")
        identity = str(observation["Id"])
        state = str(observation["ActiveState"])
        if identity != name or str(observation["LoadState"]) != "loaded":
            raise RuntimeError("Systemd returned a foreign or missing unit")
        if action in {"start", "reload"} and state != "active":
            raise RuntimeError("Systemd unit is not active")
        if action == "stop" and state != "inactive":
            raise RuntimeError("Systemd unit is not inactive")
        return {"unit": identity, "active_state": state, "job": job_result}
    finally:
        receiver.remove()
        manager.Unsubscribe()
        bus.close()


def platform_identity():
    values = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"ID", "VERSION_ID"}:
            fields = shlex.split(value)
            if len(fields) != 1 or key in values:
                raise ValueError("Invalid operating system identity")
            values[key] = fields[0]
    identity = (values.get("ID"), values.get("VERSION_ID", "").split(".")[0])
    if identity not in {("rocky", "8"), ("ubuntu", "22")}:
        raise ValueError("Unsupported reference-package operating system")
    return identity


def observer_python():
    if Path("/usr/libexec/platform-python").is_file():
        return "/usr/libexec/platform-python"
    return "/usr/bin/python3"


def contained_in(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def package_observation(name):
    if platform_identity() == ("rocky", "8"):
        import rpm

        transaction = rpm.TransactionSet()
        try:
            matches = list(transaction.dbMatch("name", name))
            if len(matches) != 1 or matches[0]["name"] != name:
                raise RuntimeError("Required RPM has no unique installed identity")
            header = matches[0]
            return {"package": header["name"], "version": header["version"],
                    "release": header["release"], "epoch": header["epoch"] or 0,
                    "architecture": header["arch"], "manager": "rpm"}
        finally:
            transaction.closeDB()
    import apt

    cache = apt.Cache()
    package = cache[name]
    if package.installed is None:
        raise RuntimeError("Required software package is not installed")
    return {"package": name, "version": package.installed.version,
            "architecture": package.installed.architecture}


def validate_request(request):
    import re
    import uuid

    if not isinstance(request, dict) or type(request.get("schema_version")) is not int or request["schema_version"] != 1 or not isinstance(request.get("parameters"), dict):
        raise ValueError("Invalid service observation request")
    if not re.fullmatch("[a-f0-9]{64}", request.get("definition_snapshot", "")):
        raise ValueError("A pinned definition snapshot is required")
    if str(uuid.UUID(request["execution_id"])) != request["execution_id"]:
        raise ValueError("A canonical execution identity is required")
    if not isinstance(request.get("action"), str):
        raise ValueError("An exact service action is required")
    if "task_id" not in request or (request["task_id"] is not None and
                                    (type(request["task_id"]) is not int or request["task_id"] <= 0)):
        raise ValueError("A task identity or explicit background execution is required")
    return request


def validate_result(request, result):
    if not isinstance(result, dict):
        raise ValueError("Service observation must be an object")
    for key in ("schema_version", "definition_snapshot", "execution_id", "task_id", "action"):
        if key not in result or type(result[key]) is not type(request[key]) or result[key] != request[key]:
            raise ValueError("Service observation is missing or belongs to another execution")
    if result.get("outcome") != "APPLIED" or not isinstance(result.get("observations"), dict) or not result["observations"]:
        raise ValueError("Service action has no verified structured observations")
    return result
