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

import hashlib
import json
import os
import pwd
import re
import subprocess
import sys
import uuid
from pathlib import Path

from observations import (atomic_json, contained_in, observer_python, package_observation,
                          platform_identity, unit_observation, validate_request, validate_result)
from content_files import render, transaction, result as action_result
from native_config import ConfigurationError


def database_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("A lowercase database identifier is required")
    return value


def connect(name):
    import psycopg2
    return psycopg2.connect(dbname=database_name(name), user="postgres", host="/var/run/postgresql",
                            connect_timeout=10)


def validate_backup(record, backup_id, source):
    if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ValueError("Invalid backup descriptor schema")
    if record.get("backup_id") != backup_id or record.get("execution_id") != backup_id:
        raise ValueError("Backup descriptor belongs to another execution")
    if str(uuid.UUID(backup_id)) != backup_id:
        raise ValueError("A canonical backup identity is required")
    for key in ("definition_snapshot", "payload_digest"):
        if not isinstance(record.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", record[key]):
            raise ValueError("Backup descriptor has no valid content identity")
    if type(record.get("task_id")) is not int or record["task_id"] <= 0:
        raise ValueError("Backup descriptor has no task identity")
    observed = record.get("source")
    if not isinstance(observed, dict) or observed.get("database") != source:
        raise ValueError("Backup identity does not match the requested source")
    if not isinstance(observed.get("instance_id"), str) or not re.fullmatch(r"[0-9]+", observed["instance_id"]):
        raise ValueError("Backup descriptor has no source instance identity")
    if type(observed.get("server_version_num")) is not int or observed["server_version_num"] < 100000:
        raise ValueError("Backup descriptor has no supported source version")
    if not isinstance(observed.get("tables"), dict):
        raise ValueError("Backup descriptor has no source table inventory")
    for table, value in observed["tables"].items():
        if (not isinstance(table, str) or not table or not isinstance(value, dict)
                or type(value.get("rows")) is not int or value["rows"] < 0
                or not isinstance(value.get("digest"), str) or not re.fullmatch(r"[a-f0-9]{64}", value["digest"])):
            raise ValueError("Invalid backup table observation")
    return record


def inventory(connection):
    import psycopg2.sql as sql

    with connection.cursor() as cursor:
        cursor.execute("SELECT system_identifier::text FROM pg_control_system()")
        instance = cursor.fetchone()[0]
        cursor.execute("SELECT current_database(), current_setting('server_version_num')")
        database, version = cursor.fetchone()
        cursor.execute("SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                       "WHERE c.relkind='r' AND n.nspname NOT IN ('pg_catalog','information_schema') "
                       "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY n.nspname,c.relname")
        tables = cursor.fetchall()
        rows = {}
        for schema, table in tables:
            cursor.execute(sql.SQL("SELECT to_jsonb(t)::text FROM {}.{} t").format(
                sql.Identifier(schema), sql.Identifier(table)))
            hashes = sorted(hashlib.sha256(value[0].encode("utf-8")).hexdigest() for value in cursor.fetchall())
            rows[schema + "." + table] = {"rows": len(hashes),
                "digest": hashlib.sha256("\n".join(hashes).encode("ascii")).hexdigest()}
        return {"instance_id": instance, "database": database, "server_version_num": int(version), "tables": rows}


def worker(request):
    if os.geteuid() != pwd.getpwnam("postgres").pw_uid:
        raise ValueError("Database observations must execute as the database OS account")
    action = request["action"]
    parameters = request["parameters"]
    port = int(parameters.get("port", "5432"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PostgreSQL port")
    os.environ["PGPORT"] = str(port)
    source = database_name(parameters.get("database", "postgres"))
    if action == "configuration":
        with connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_file_settings WHERE error IS NOT NULL")
                if cursor.fetchone()[0] != 0:
                    raise ConfigurationError("PostgreSQL reported configuration file errors")
                cursor.execute("SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL")
                if cursor.fetchone()[0] != 0:
                    raise ConfigurationError("PostgreSQL reported authentication file errors")
                cursor.execute("SELECT current_setting('port'), current_setting('config_file'), current_setting('hba_file'), current_setting('ident_file')")
                row = cursor.fetchone()
                return {"port": int(row[0]), "config_file": row[1], "hba_file": row[2], "ident_file": row[3],
                        "configuration_errors": 0, "authentication_errors": 0}
    if action in {"health", "version"}:
        with connect(source) as connection:
            return inventory(connection)
    root = Path("/var/lib/pgsql" if platform_identity() == ("rocky", "8") else "/var/lib/postgresql")
    base = Path(parameters.get("backup_directory") or str(root / "ambari-backups"))
    if not base.is_absolute() or base.is_symlink() or not contained_in(base, root):
        raise ValueError("Backup storage must be contained in the PostgreSQL persistent directory")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if action == "backup":
        backup_id = str(uuid.UUID(request["execution_id"]))
        descriptor = base / (backup_id + ".json")
        payload = base / (backup_id + ".dump")
        if payload.exists() or descriptor.exists():
            raise ValueError("Existing backup requires explicit reconciliation, not overwrite")
        connection = connect(source)
        try:
            with connection.cursor() as cursor:
                cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute("SELECT pg_export_snapshot()")
                snapshot = cursor.fetchone()[0]
            observed = inventory(connection)
            command = ["/usr/bin/pg_dump", "--format=custom", "--snapshot=" + snapshot,
                       "--file=" + str(payload), "--dbname=" + source]
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if result.returncode != 0 or not payload.is_file() or payload.stat().st_size == 0:
                raise RuntimeError("Backup execution has no complete payload")
            content_digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            record = {"schema_version": 1, "backup_id": backup_id, "execution_id": request["execution_id"],
                      "definition_snapshot": request["definition_snapshot"], "task_id": request["task_id"],
                      "payload_digest": content_digest, "source": observed}
            atomic_json(descriptor, record)
            if json.loads(descriptor.read_text()) != record:
                raise RuntimeError("Backup descriptor could not be verified")
            return {"backup": record, "payload_bytes": payload.stat().st_size,
                    "verification": "PAYLOAD_AND_SOURCE_SNAPSHOT"}
        finally:
            connection.close()
    if action == "restore":
        backup_id = str(uuid.UUID(parameters.get("backup_id", "")))
        target = database_name(parameters.get("restore_database"))
        if target == source or target in {"postgres", "template0", "template1"}:
            raise ValueError("Restore cannot target a source or system database")
        descriptor = base / (backup_id + ".json")
        payload = base / (backup_id + ".dump")
        if descriptor.is_symlink() or payload.is_symlink():
            raise ValueError("Backup files cannot be symbolic links")
        record = validate_backup(json.loads(descriptor.read_text(encoding="utf-8")), backup_id, source)
        if hashlib.sha256(payload.read_bytes()).hexdigest() != record["payload_digest"]:
            raise ValueError("Backup payload digest does not match")
        import psycopg2.sql as sql
        admin = connect("postgres")
        admin.autocommit = True
        try:
            with admin.cursor() as cursor:
                cursor.execute("SELECT system_identifier::text FROM pg_control_system()")
                target_instance = cursor.fetchone()[0]
                if target_instance == record["source"]["instance_id"]:
                    raise ValueError("Recovery must target an isolated PostgreSQL instance")
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=%s)", (target,))
                if cursor.fetchone()[0]:
                    raise ValueError("Restore target already exists; verify or remove it explicitly")
                cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target)))
            result = subprocess.run(["/usr/bin/pg_restore", "--exit-on-error", "--single-transaction",
                                     "--dbname=" + target, str(payload)], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, check=False)
            if result.returncode != 0:
                raise RuntimeError("Restore execution did not complete")
            with connect(target) as restored:
                observed = inventory(restored)
            if (observed["tables"] != record["source"]["tables"] or observed["instance_id"] != target_instance
                or observed["server_version_num"] // 10000 != record["source"]["server_version_num"] // 10000):
                raise RuntimeError("Restored data does not match the source snapshot")
            return {"backup_id": backup_id, "payload_digest": record["payload_digest"],
                    "source": record["source"], "target": observed, "verification": "RESTORED_TABLE_DIGESTS"}
        finally:
            admin.close()
    raise ValueError("Unsupported database observation")


def observe_database(request):
    process = subprocess.run(["/usr/sbin/runuser", "-u", "postgres", "--", observer_python(),
                              str(Path(__file__).resolve()), "--worker"],
                             input=json.dumps(request).encode("utf-8"), stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=3500, check=False)
    result = json.loads(process.stdout)
    validate_result(request, result)
    if process.returncode != 0:
        raise RuntimeError("Database operation did not complete")
    return result["observations"]


def configure_content(request, rocky, unit, activate=False):
    data = Path("/var/lib/pgsql/data" if rocky else "/var/lib/postgresql/14/main")
    root = data if rocky else Path("/etc/postgresql/14/main")
    port = int(request["parameters"].get("port", "5432"))
    if not 1 <= port <= 65535:
        raise ConfigurationError("PostgreSQL port must be between 1 and 65535")
    variables = {"data_directory": str(data), "hba_file": str(root / "pg_hba.conf"),
                 "ident_file": str(root / "pg_ident.conf"), "socket_directory": "/var/run/postgresql", "port": port}
    contents = {}
    for kind, filename in (("postgresql-conf", "postgresql.conf"), ("postgresql-hba", "pg_hba.conf"),
                           ("postgresql-ident", "pg_ident.conf")):
        value = render(request["parameters"], kind, variables)
        if value is not None:
            contents[filename] = value
    if not contents:
        return None
    if unit != ("postgresql.service" if rocky else "postgresql@14-main.service"):
        raise ConfigurationError("Content management requires the platform's declared PostgreSQL instance")
    binary = "/usr/bin/postgres" if rocky else "/usr/lib/postgresql/14/bin/postgres"
    def validate(staged):
        conf = staged.get("postgresql.conf", root / "postgresql.conf")
        for key, expected in (("port", str(port)), ("data_directory", str(data)),
                              ("hba_file", str(root / "pg_hba.conf")), ("ident_file", str(root / "pg_ident.conf")),
                              ("unix_socket_directories", "/var/run/postgresql")):
            # -C is PostgreSQL's documented single-setting query, not a log/status parser.
            process = subprocess.run(["/usr/sbin/runuser", "-u", "postgres", "--", binary,
                "-D", str(data), "-c", "config_file=" + str(conf), "-C", key],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False)
            if process.returncode != 0 or process.stdout.decode("utf-8").strip() != expected:
                raise ConfigurationError("Invalid PostgreSQL configuration or conflicting managed setting: " + key)
    with transaction(root, contents, validate, "postgres") as files:
        observed = {"files": files, "port": port}
        if activate:
            try:
                observed["systemd"] = unit_observation(unit, "start")
                observed["database"] = observe_database(dict(request, action="configuration"))
                if observed["database"]["port"] != port:
                    raise ConfigurationError("PostgreSQL started with a different port")
                for key, filename in (("config_file", "postgresql.conf"), ("hba_file", "pg_hba.conf"),
                                      ("ident_file", "pg_ident.conf")):
                    if observed["database"][key] != str(root / filename):
                        raise ConfigurationError("PostgreSQL loaded a different managed file: " + key)
            except Exception:
                unit_observation(unit, "stop")
                raise
        return observed


def execute(request):
    action = request["action"]
    rocky = platform_identity() == ("rocky", "8")
    unit = request["parameters"].get("unit") or ("postgresql.service" if rocky else "postgresql@14-main.service")
    if not (unit == "postgresql.service" or re.fullmatch(r"postgresql@[a-zA-Z0-9_-]+\.service", unit)):
        raise ValueError("Invalid PostgreSQL unit identity")
    observed = {"software": package_observation("postgresql-server" if rocky else "postgresql-14")}
    if action == "package":
        return action_result(request, "APPLIED", observed)
    if action == "stop":
        observed["systemd"] = unit_observation(unit, action)
    elif action in {"configure", "start"}:
        if rocky:
            data = Path("/var/lib/pgsql/data")
            marker = data / "PG_VERSION"
            if data.is_symlink():
                raise ValueError("PostgreSQL data must not be a symbolic link")
            if not marker.is_file():
                if data.exists() and any(data.iterdir()):
                    raise ValueError("Existing uninitialized PostgreSQL data requires reconciliation")
                account = pwd.getpwnam("postgres")
                data.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chown(str(data), account.pw_uid, account.pw_gid)
                result = subprocess.run(["/usr/sbin/runuser", "-u", "postgres", "--",
                                         "/usr/bin/initdb", "-D", str(data), "--auth-local=peer",
                                         "--auth-host=scram-sha-256"], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=120, check=False)
                if result.returncode != 0:
                    raise RuntimeError("PostgreSQL initialization did not complete")
            expected = observed["software"]["version"].split(".")[0]
            if marker.read_text(encoding="ascii").strip() != expected:
                raise RuntimeError("PostgreSQL data version does not match the installed package")
        configured = configure_content(request, rocky, unit, activate=action == "start")
        observed["configuration"] = configured or {"mode": "OS_MANAGED", "unit": unit}
        if action == "start" and configured is None:
            observed["systemd"] = unit_observation(unit, "start")
    elif action in {"health", "version", "backup", "restore"}:
        if action == "health":
            observed["systemd"] = unit_observation(unit)
            if observed["systemd"]["active_state"] != "active":
                raise RuntimeError("PostgreSQL is not active")
        process = subprocess.run(["/usr/sbin/runuser", "-u", "postgres", "--", observer_python(),
                                  str(Path(__file__).resolve()), "--worker"],
                                 input=json.dumps(request).encode("utf-8"), stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=3500, check=False)
        result = json.loads(process.stdout)
        validate_result(request, result)
        if process.returncode != 0 or result.get("execution_id") != request["execution_id"] or result.get("outcome") != "APPLIED":
            raise RuntimeError("Database result is missing or foreign")
        observed["database"] = result["observations"]
    else:
        raise ValueError("Unsupported PostgreSQL operation")
    return action_result(request, "APPLIED", observed)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--worker":
        request = validate_request(json.load(sys.stdin))
        try:
            print(json.dumps(action_result(request, "APPLIED", worker(request)), allow_nan=False))
        except Exception as error:
            print(json.dumps(action_result(request, "UNRESOLVED", {"error_type": type(error).__name__})))
            raise SystemExit(1)
    else:
        request = validate_request(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
        try:
            result = execute(request)
        except Exception as error:
            details = {"error_type": type(error).__name__}
            if isinstance(error, ConfigurationError):
                details["configuration_error"] = str(error)
            atomic_json(sys.argv[2], action_result(request, "UNRESOLVED", details))
            raise SystemExit(1)
        atomic_json(sys.argv[2], result)
