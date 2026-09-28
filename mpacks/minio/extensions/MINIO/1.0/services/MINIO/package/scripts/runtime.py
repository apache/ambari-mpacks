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
from pathlib import Path

from managed_runtime import directory, no_links, owned_file, path_value, port_value, reload_units, result, unit
from observations import atomic_json, unit_observation, validate_request
from verified_archive import digest_file, install_archive, verify_install

VERSION = "RELEASE.2025-10-15T17-29-55Z"
COMMIT = "9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a"
SOURCE_SHA512 = "9b4ff0a68f615a1fd646b0ef0125930f71dfa6afbba4a5eb819a5d5f016c7363fefb9c6d45e0afc4742ffb6c1bec5987c471c3ed2bf0a32f68749546b9a9144a"
MINIO_SHA256 = "36a65e472ca0a0a3a209ca0ab10d1966e8e089d92b7466a7e45df8d1e4d6708f"
CHECK_SHA256 = "109e7e9ec52bcc3816d082309b24ddc1aa424b748c02abf899b7044c01e5eb40"
SOURCE_URL = "https://codeload.github.com/minio/minio/tar.gz/" + COMMIT
PREFIX = "minio-" + COMMIT
REQUIRED = ["go.mod", "go.sum", "main.go"]
HOME = Path("/opt/ambari-mpacks/minio") / VERSION
CONF = Path("/etc/minio/ambari")
DATA = Path("/var/lib/minio")
GO_CACHE = Path("/var/cache/ambari-mpacks/minio-go")


class CheckFailure(Exception):
    def __init__(self, observation):
        self.observation = observation


class BuildFailure(CheckFailure):
    pass


def settings(parameters):
    role = parameters["component"]
    if role not in {"server", "check"}:
        raise ValueError("Unknown MinIO component")
    host = parameters["server_host"]
    from managed_runtime import host_value
    host = host_value(host)
    assigned = host_value(parameters["hostname"])
    if role == "server" and assigned != host:
        raise ValueError("MinIO server placement differs from the assigned host")
    api, console = port_value(parameters["api_port"]), port_value(parameters["console_port"])
    if api == console:
        raise ValueError("MinIO API and console ports must differ")
    storage = path_value(parameters["data_directory"], ("/var/lib/minio/",))
    go_home = path_value(parameters["go_home"], ("/usr/local/go", "/opt/"))
    user, password = parameters["root_user"], parameters["root_password"]
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,31}", user):
        raise ValueError("An explicit MinIO root user is required")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024 or "\x00" in password:
        raise ValueError("An explicit MinIO root password is required")
    return role, host, api, console, storage, go_home, user, password


def built():
    source = verify_install(HOME, "minio", VERSION, SOURCE_SHA512, REQUIRED)
    for name, expected in (("minio", MINIO_SHA256), ("check-s3", CHECK_SHA256)):
        path = HOME / "bin" / name
        no_links(path)
        if not path.is_file() or digest_file(path, "sha256") != expected:
            raise ValueError("MinIO compiled binary differs from its pinned source build")
    return {"source_commit": COMMIT, "source_sha512": source["archive_sha512"],
            "binary_sha256": MINIO_SHA256, "check_sha256": CHECK_SHA256}


def go_environment():
    environment = {key: value for key, value in os.environ.items() if key not in
                   {"PYTHONPATH", "PYTHONHOME", "GOFLAGS", "GOTOOLCHAIN", "GOPROXY", "GOSUMDB", "GOOS", "GOARCH", "CGO_ENABLED"}}
    environment.update(GOTOOLCHAIN="go1.24.8", GOPROXY="https://proxy.golang.org",
                       GOSUMDB="sum.golang.org", GOOS="linux", GOARCH="arm64", CGO_ENABLED="0",
                       GOCACHE=str(GO_CACHE / "build"), GOMODCACHE=str(GO_CACHE / "modules"),
                       GOPATH=str(GO_CACHE / "path"))
    return environment


def build(parameters):
    role, host, api, console, storage, go_home, user, password = settings(parameters)
    source = install_archive("minio", VERSION, parameters.get("source_url") or SOURCE_URL,
                             SOURCE_SHA512, PREFIX, REQUIRED, maximum_archive=128 * 1024 ** 2)
    executable = go_home / "bin/go"
    no_links(executable)
    if not executable.is_file():
        raise ValueError("A Go toolchain is required to build MinIO from source")
    binaries = HOME / "bin"
    no_links(binaries)
    binaries.mkdir(exist_ok=True, mode=0o755)
    for path in (GO_CACHE, GO_CACHE / "build", GO_CACHE / "modules", GO_CACHE / "path"):
        directory(path, "root", 0o700)
    environment = go_environment()
    flags = ("-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z "
             "-X github.com/minio/minio/cmd.ReleaseTag=" + VERSION + " "
             "-X github.com/minio/minio/cmd.CommitID=" + COMMIT + " "
             "-X github.com/minio/minio/cmd.ShortCommitID=" + COMMIT[:12] + " "
             "-X github.com/minio/minio/cmd.CopyrightYear=2025")
    commands = (("minio", MINIO_SHA256, [str(executable), "build", "-tags", "kqueue", "-trimpath",
                 "-buildvcs=false", "-ldflags", flags]),
                ("check-s3", CHECK_SHA256, [str(executable), "build", "-trimpath", "-buildvcs=false",
                 "-ldflags", "-s -w"]))
    for name, expected, command in commands:
        destination = binaries / name
        no_links(destination)
        if destination.exists():
            if digest_file(destination, "sha256") != expected:
                raise ValueError("An existing MinIO build differs from its pinned digest")
            continue
        with tempfile.TemporaryDirectory(prefix=".build-", dir=str(binaries)) as work:
            target = Path(work) / name
            source_file = "." if name == "minio" else str(Path(__file__).with_name("check_s3.go"))
            process = subprocess.run(command + ["-o", str(target), source_file], cwd=str(HOME), env=environment,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=7200, check=False)
            observed_digest = digest_file(target, "sha256") if target.is_file() else None
            if process.returncode != 0 or observed_digest != expected:
                raise BuildFailure({"build_component": name, "exit_code": process.returncode,
                                    "expected_sha256": expected, "observed_sha256": observed_digest})
            os.replace(str(target), str(destination))
            destination.chmod(0o755)
    return built()


def configure(parameters):
    role, host, api, console, storage, go_home, user, password = settings(parameters)
    if role != "server":
        raise ValueError("A service check cannot configure MinIO")
    built()
    for path in (CONF, DATA, storage):
        directory(path, "minio")
    runtime = {"binary": str(HOME / "bin/minio"), "data": str(storage), "api_port": api,
               "console_port": console, "root_user": user, "root_password": password}
    owned_file(CONF / "runtime.json", json.dumps(runtime, sort_keys=True), "minio", 0o600)
    owned_file(CONF / "launcher.py", Path(__file__).with_name("launcher.py").read_text(), "minio", 0o500)
    unit("ambari-minio.service", "minio", Path("/usr/libexec/platform-python"),
         {"PYTHONDONTWRITEBYTECODE": "1"}, DATA, str(CONF / "launcher.py"))
    reload_units()
    return {"server": host, "api_port": api, "console_port": console, "data_directory": str(storage)}


def check(request):
    parameters = request["parameters"]
    role, host, api, console, storage, go_home, user, password = settings(parameters)
    built()
    directory(DATA, "minio")
    account = pwd.getpwnam("minio")
    with tempfile.TemporaryDirectory(prefix=".check-", dir=str(DATA)) as work:
        os.chown(work, account.pw_uid, account.pw_gid)
        source, destination = Path(work) / "request.json", Path(work) / "result.json"
        owned_file(source, json.dumps({"schema_version": 1, "execution_id": request["execution_id"],
                   "endpoint": host + ":" + str(api), "access_key": user, "secret_key": password,
                   "tls": False}), "minio", 0o600)
        process = subprocess.run(["/usr/sbin/runuser", "-u", "minio", "--", str(HOME / "bin/check-s3"),
                                  str(source), str(destination)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=120, check=False)
        if not destination.is_file() or destination.stat().st_size > 16384:
            raise RuntimeError("Missing bounded MinIO SDK observation")
        observed = json.loads(destination.read_text())
    if (not isinstance(observed, dict) or type(observed.get("schema_version")) is not int
            or observed["schema_version"] != 1 or observed.get("execution_id") != request["execution_id"]
            or observed.get("outcome") not in {"APPLIED", "UNRESOLVED"}
            or observed.get("stage") not in {"client", "create", "write", "read", "verified", "cleanup"}
            or not isinstance(observed.get("bucket"), str) or not isinstance(observed.get("object"), str)
            or not isinstance(observed.get("sha256"), str) or type(observed.get("cleanup")) is not bool):
        raise ValueError("Invalid MinIO SDK observation")
    if process.returncode != 0 or observed["outcome"] != "APPLIED" or observed["stage"] != "verified" or not observed["cleanup"]:
        raise CheckFailure({"stage": observed["stage"], "bucket": observed["bucket"],
                            "cleanup": observed["cleanup"]})
    if not re.fullmatch(r"ambari-mpack-[0-9a-f]{32}", observed["bucket"]) or observed["object"] != "probe":
        raise ValueError("Foreign MinIO object identity")
    unique = observed["bucket"].split("ambari-mpack-", 1)[1]
    expected = hashlib.sha256(("ambari-mpack:" + request["execution_id"] + ":" + unique).encode()).hexdigest()
    if observed["sha256"] != expected:
        raise ValueError("MinIO object digest differs from the owned request")
    return {"bucket": observed["bucket"], "object": observed["object"],
            "sha256": expected, "cleanup": True}


def execute(request):
    parameters, action = request["parameters"], request["action"]
    role, host, api, console, storage, go_home, user, password = settings(parameters)
    if action == "install":
        return {"software": build(parameters)}
    if action == "version":
        return {"software": built()}
    if action == "configure":
        return {"configuration": configure(parameters)}
    if action == "check":
        return {"s3": check(request)}
    if role != "server" or action not in {"start", "stop", "status"}:
        raise ValueError("Unsupported MinIO action")
    observed = unit_observation("ambari-minio.service", None if action == "status" else action)
    if action == "status" and observed["active_state"] != "active":
        raise RuntimeError("MinIO is not active")
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
