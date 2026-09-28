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

import base64
import hashlib
import ipaddress
import json
import os
import pwd
import re
import ssl
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from managed_runtime import directory, host_value, no_links, owned_file, path_value, port_value, reload_units, result, unit
from observations import atomic_json, unit_observation, validate_request
from verified_archive import digest_file, install_archive, verify_install

VERSION = "9.5.4"
SHA512 = "51d42530da01deb81b538c2d4c27f6f023f1d11d9415865b5dbabab7d6699831f8fc8aaffb1f73d2d5915a212d613d9ee0e44debce361a25a7e4b59663b1701c"
URL = "https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-9.5.4-linux-aarch64.tar.gz"
REQUIRED = ["bin/elasticsearch", "bin/elasticsearch-keystore", "config/jvm.options",
            "lib/elasticsearch-9.5.4.jar", "jdk/bin/java"]
HOME = Path("/opt/ambari-mpacks/elasticsearch/9.5.4")
CONF = Path("/etc/elasticsearch/ambari")
DATA = Path("/var/lib/elasticsearch/ambari")
LOGS = Path("/var/log/elasticsearch/ambari")


class CheckFailure(Exception):
    def __init__(self, stage, index="", cleanup=True):
        self.observation = {"stage": stage, "index": index, "cleanup": cleanup}


def settings(parameters):
    role = parameters["component"]
    if role not in {"node", "check"}:
        raise ValueError("Unknown Elasticsearch component")
    host = host_value(parameters["node_host"])
    assigned = host_value(parameters["hostname"])
    if role == "node" and assigned != host:
        raise ValueError("Elasticsearch node placement differs from the assigned host")
    http, transport = port_value(parameters["http_port"]), port_value(parameters["transport_port"])
    if http == transport:
        raise ValueError("Elasticsearch HTTP and transport ports must differ")
    cluster = parameters["cluster_name"]
    if not isinstance(cluster, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", cluster):
        raise ValueError("Invalid Elasticsearch cluster identity")
    storage = path_value(parameters["data_directory"], ("/var/lib/elasticsearch/",))
    heap = parameters["heap_size"]
    if not isinstance(heap, str) or not re.fullmatch(r"[1-9][0-9]*[gG]", heap):
        raise ValueError("Invalid Elasticsearch heap size")
    password = parameters["admin_password"]
    if not isinstance(password, str) or not 12 <= len(password) <= 1024 or any(
            character in password for character in "\x00\r\n"):
        raise ValueError("An explicit Elasticsearch administrator password is required")
    return role, host, http, transport, cluster, storage, heap.upper(), password


def installed():
    return verify_install(HOME, "elasticsearch", VERSION, SHA512, REQUIRED)


def _run(command, timeout=120, environment=None, input_value=None):
    process = subprocess.run(command, input=input_value, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=timeout, env=environment, check=False)
    if process.returncode:
        raise RuntimeError("Elasticsearch setup command failed")


def certificate(host):
    key, cert, marker = CONF / "node.key", CONF / "node.crt", CONF / "certificate.json"
    for path in (key, cert, marker):
        no_links(path)
    regenerate = not any(path.exists() for path in (key, cert, marker))
    reuse_key = False
    if not regenerate:
        if not all(path.is_file() for path in (key, cert, marker)):
            raise ValueError("Partial Elasticsearch TLS identity exists")
        receipt = json.loads(marker.read_text())
        if type(receipt.get("schema_version")) is not int or receipt["schema_version"] not in {1, 2} or receipt != {"schema_version": receipt["schema_version"], "hostname": host,
                       "certificate_sha256": digest_file(cert, "sha256")}:
            raise ValueError("Elasticsearch TLS identity differs from the assigned host")
        if receipt["schema_version"] == 1 and not (DATA / "administrator.json").exists():
            owned_file(CONF / "node.pre-v2.crt", cert.read_text(), "root", 0o600)
            atomic_json(CONF / "certificate.pre-v2.json", receipt)
            regenerate, reuse_key = True, True
    if regenerate:
        try:
            ipaddress.ip_address(host)
            subject = "IP:" + host
        except ValueError:
            subject = "DNS:" + host
        with tempfile.TemporaryDirectory(prefix=".certificate-", dir=str(CONF)) as work:
            temporary_key, temporary_cert = Path(work) / "node.key", Path(work) / "node.crt"
            config = Path(work) / "openssl.cnf"
            config.write_text("[req]\nprompt=no\ndistinguished_name=identity\nx509_extensions=node_extensions\n"
                "[identity]\nCN=" + host + "\n[node_extensions]\nsubjectAltName=" + subject + "\n"
                "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n"
                "extendedKeyUsage=serverAuth,clientAuth\n")
            command = ["/usr/bin/openssl", "req", "-x509", "-nodes", "-sha256", "-days", "3650",
                       "-config", str(config), "-out", str(temporary_cert)]
            command += ["-key", str(key)] if reuse_key else ["-newkey", "rsa:3072", "-keyout", str(temporary_key)]
            _run(command)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_cert_chain(str(temporary_cert), str(key if reuse_key else temporary_key))
            account = pwd.getpwnam("elasticsearch")
            replacements = [(temporary_cert, cert, 0o640)]
            if not reuse_key:
                replacements.insert(0, (temporary_key, key, 0o600))
            for source, destination, mode in replacements:
                source.chmod(mode)
                os.chown(str(source), account.pw_uid, account.pw_gid)
                os.replace(str(source), str(destination))
        atomic_json(marker, {"schema_version": 2, "hostname": host,
                    "certificate_sha256": digest_file(cert, "sha256")})
    context = ssl.create_default_context(cafile=str(cert))
    context.load_cert_chain(str(cert), str(key))
    return digest_file(cert, "sha256")


def keystore(password):
    marker = CONF / "bootstrap.json"
    no_links(marker)
    digest = hashlib.sha256(password.encode()).hexdigest()
    identity = {"schema_version": 1, "password_sha256": digest}
    path = CONF / "elasticsearch.keystore"
    no_links(path)
    if marker.exists():
        if json.loads(marker.read_text()) != identity or not path.is_file():
            raise ValueError("Elasticsearch bootstrap credential differs")
        return
    if path.exists():
        raise ValueError("Unowned Elasticsearch keystore exists")
    environment = dict(os.environ, ES_PATH_CONF=str(CONF), ES_JAVA_HOME=str(HOME / "jdk"))
    command = ["/usr/sbin/runuser", "-m", "-u", "elasticsearch", "--",
               str(HOME / "bin/elasticsearch-keystore")]
    _run(command + ["create"], environment=environment)
    _run(command + ["add", "-x", "bootstrap.password"], environment=environment,
         input_value=(password + "\n").encode())
    if not path.is_file():
        raise RuntimeError("Elasticsearch keystore was not created")
    atomic_json(marker, identity)


def configure(parameters):
    from native_config import content, jvm_options, properties, yaml_properties
    role, host, http, transport, cluster, storage, heap, password = settings(parameters)
    if role == "check":
        raise ValueError("A service check cannot configure Elasticsearch")
    installed()
    for path in (CONF, DATA, LOGS, storage, DATA / "tmp"):
        directory(path, "elasticsearch")
    for source in (HOME / "config").iterdir():
        if source.name in {"elasticsearch.yml", "elasticsearch.keystore"} or source.is_dir():
            continue
        if source.is_symlink() or not source.is_file():
            raise ValueError("Unexpected Elasticsearch configuration member")
        target = CONF / source.name
        owned_file(target, source.read_text(), "elasticsearch")
    certificate_hash = certificate(host)
    lines = ["cluster.name: " + cluster, "node.name: " + host,
             "network.host: " + host, "http.port: " + str(http),
             "transport.port: " + str(transport), "discovery.type: single-node",
             "path.data: " + str(storage), "path.logs: " + str(LOGS),
             "xpack.security.enabled: true", "xpack.security.autoconfiguration.enabled: false",
             "xpack.security.enrollment.enabled: false", "xpack.security.http.ssl.enabled: true",
             "xpack.security.http.ssl.key: " + str(CONF / "node.key"),
             "xpack.security.http.ssl.certificate: " + str(CONF / "node.crt"),
             "xpack.security.http.ssl.certificate_authorities: [" + str(CONF / "node.crt") + "]",
             "xpack.security.transport.ssl.enabled: true",
             "xpack.security.transport.ssl.verification_mode: certificate",
             "xpack.security.transport.ssl.key: " + str(CONF / "node.key"),
             "xpack.security.transport.ssl.certificate: " + str(CONF / "node.crt"),
             "xpack.security.transport.ssl.certificate_authorities: [" + str(CONF / "node.crt") + "]"]
    managed = dict(line.split(": ", 1) for line in lines)
    for key in ("xpack.security.http.ssl.certificate_authorities", "xpack.security.transport.ssl.certificate_authorities"):
        managed[key] = json.dumps([str(CONF / "node.crt")])
    values = properties(parameters, "elasticsearch-settings", managed,
                        reserved=("xpack.security.", "discovery.", "cluster.initial_master_nodes"))
    owned_file(CONF / "elasticsearch.yml", yaml_properties(values), "elasticsearch")
    options = jvm_options(parameters, "elasticsearch-jvm", "# Additional JVM options, one per line.\n")
    directory(CONF / "jvm.options.d", "elasticsearch")
    owned_file(CONF / "jvm.options.d/99-ambari.options", "\n".join(options) + "\n", "elasticsearch")
    owned_file(CONF / "log4j2.properties", content(parameters, "elasticsearch-log4j2",
               (HOME / "config/log4j2.properties").read_text()), "elasticsearch")
    keystore(password)
    maximum = Path("/proc/sys/vm/max_map_count")
    if not maximum.is_file() or int(maximum.read_text().strip()) < 262144:
        raise ValueError("Elasticsearch requires vm.max_map_count >= 262144")
    unit("ambari-elasticsearch.service", "elasticsearch", HOME / "bin/elasticsearch",
         {"ES_PATH_CONF": str(CONF), "ES_JAVA_HOME": str(HOME / "jdk"),
          "ES_TMPDIR": str(DATA / "tmp"), "ES_JAVA_OPTS": "-Xms" + heap + " -Xmx" + heap}, DATA)
    reload_units()
    return {"cluster": cluster, "node": host, "http_port": http, "certificate_sha256": certificate_hash}


def api(host, port, password, path, method="GET", body=None):
    base = "https://" + host + ":" + str(port)
    context = ssl.create_default_context(cafile=str(CONF / "node.crt"))
    secret = base64.b64encode(("elastic:" + password).encode()).decode()
    headers = {"Authorization": "Basic " + secret, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                         urllib.request.HTTPSHandler(context=context))
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with opener.open(request, timeout=15) as response:
        payload = response.read(1024 * 1024 + 1)
        if response.status not in {200, 201} or len(payload) > 1024 * 1024:
            raise ValueError("Invalid bounded Elasticsearch API response")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Missing Elasticsearch API object")
    return value


def authenticate(host, port, password):
    value = api(host, port, password, "/_security/_authenticate")
    if value.get("username") != "elastic" or not isinstance(value.get("roles"), list) or "superuser" not in value["roles"]:
        raise ValueError("Elasticsearch administrator identity differs")
    return {"username": "elastic", "role": "superuser"}


def bootstrap(parameters):
    role, host, http, transport, cluster, storage, heap, password = settings(parameters)
    marker = DATA / "administrator.json"
    no_links(marker)
    identity = {"schema_version": 1, "cluster": cluster,
                "password_sha256": hashlib.sha256(password.encode()).hexdigest()}
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise ValueError("Elasticsearch administrator credential differs from its retained identity")
    deadline = time.monotonic() + 180
    while True:
        try:
            authenticate(host, http, password)
            break
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise RuntimeError("Elasticsearch authentication did not become ready")
            time.sleep(3)
    if not marker.exists():
        value = api(host, http, password, "/_security/user/elastic/_password", "POST",
                    {"password": password})
        if value:
            raise ValueError("Unexpected Elasticsearch password update response")
        authenticate(host, http, password)
        atomic_json(marker, identity)
    return {"administrator": "elastic", "cluster": cluster}


def check(request):
    role, host, http, transport, cluster, storage, heap, password = settings(request["parameters"])
    root = api(host, http, password, "/")
    if (root.get("cluster_name") != cluster or not isinstance(root.get("version"), dict)
            or root["version"].get("number") != VERSION):
        raise CheckFailure("identity")
    authenticate(host, http, password)
    health = api(host, http, password, "/_cluster/health")
    if (health.get("cluster_name") != cluster or health.get("timed_out") is not False
            or health.get("status") not in {"green", "yellow"}
            or type(health.get("number_of_nodes")) is not int or health["number_of_nodes"] != 1):
        raise CheckFailure("health")
    index = "ambari-mpack-" + request["execution_id"].replace("-", "")
    stage, created, cleanup = "create", False, True
    failure = False
    try:
        opened = api(host, http, password, "/" + index, "PUT", {})
        if opened.get("acknowledged") is not True or opened.get("index") != index:
            raise ValueError("Elasticsearch index creation identity differs")
        created = True
        stage = "write"
        document = api(host, http, password, "/" + index + "/_doc/" + request["execution_id"] + "?refresh=wait_for",
                       "PUT", {"execution_id": request["execution_id"]})
        if (document.get("_index") != index or document.get("_id") != request["execution_id"]
                or document.get("result") != "created"):
            raise ValueError("Elasticsearch document write identity differs")
        stage = "read"
        read = api(host, http, password, "/" + index + "/_doc/" + request["execution_id"])
        if (read.get("_index") != index or read.get("_id") != request["execution_id"]
                or read.get("found") is not True
                or read.get("_source") != {"execution_id": request["execution_id"]}):
            raise ValueError("Elasticsearch document readback differs")
    except Exception:
        failure = True
    finally:
        if created:
            try:
                removed = api(host, http, password, "/" + index, "DELETE")
                cleanup = removed.get("acknowledged") is True
            except Exception:
                cleanup = False
    if failure or not cleanup:
        raise CheckFailure(stage if cleanup else "cleanup", index, cleanup)
    return {"cluster": cluster, "status": health["status"], "number_of_nodes": 1,
            "index": index, "document_id": request["execution_id"], "cleanup": True}


def execute(request):
    parameters, action = request["parameters"], request["action"]
    role, host, http, transport, cluster, storage, heap, password = settings(parameters)
    if action == "install":
        return {"software": install_archive("elasticsearch", VERSION, parameters.get("binary_url") or URL,
                SHA512, "elasticsearch-9.5.4", REQUIRED, maximum_archive=1024 ** 3)}
    if action == "version":
        return {"software": installed()}
    if action == "configure":
        return {"configuration": configure(parameters)}
    if action == "check":
        return {"index": check(request)}
    if role != "node" or action not in {"start", "stop", "status"}:
        raise ValueError("Unsupported Elasticsearch action")
    observed = unit_observation("ambari-elasticsearch.service", None if action == "status" else action)
    if action == "status" and observed["active_state"] != "active":
        raise RuntimeError("Elasticsearch node is not active")
    if action == "status":
        marker = DATA / "administrator.json"
        no_links(marker)
        expected = {"schema_version": 1, "cluster": cluster,
                    "password_sha256": hashlib.sha256(password.encode()).hexdigest()}
        if not marker.is_file() or json.loads(marker.read_text()) != expected:
            raise RuntimeError("Elasticsearch administrator initialization is unresolved")
    if action == "start":
        return {"systemd": observed, "bootstrap": bootstrap(parameters)}
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
