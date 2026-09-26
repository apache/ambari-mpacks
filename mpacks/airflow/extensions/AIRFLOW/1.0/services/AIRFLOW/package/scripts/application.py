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

import importlib.metadata
import json
import time
import urllib.error
from pathlib import Path

from managed_runtime import json_http, main

VERSION = "3.3.2"


class AirflowNotReady(ValueError):
    pass


def version():
    expected = {"apache-airflow": VERSION, "apache-airflow-core": VERSION,
                "apache-airflow-providers-fab": "3.9.0", "apache-airflow-providers-postgres": "7.0.2"}
    observed = {name: importlib.metadata.version(name) for name in expected}
    if observed != expected:
        raise ValueError("Installed Airflow distribution does not match its pinned constraints")
    return observed


def database(parameters, initialize=False):
    from sqlalchemy import inspect, text
    from alembic.migration import MigrationContext
    from airflow import settings
    from airflow.utils import db
    engine = settings.get_engine()
    with engine.connect() as connection:
        major = int(connection.execute(text("SHOW server_version_num")).scalar_one()) // 10000
        name = connection.execute(text("SELECT current_database()")).scalar_one()
        if name != parameters["database_name"] or major not in {14, 15, 16, 17, 18}:
            raise ValueError("Airflow requires its selected dedicated PostgreSQL 14-18 database")
        current = set(MigrationContext.configure(connection).get_current_heads())
        expected = set(db._get_script_object().get_heads())
        if not expected:
            raise ValueError("Airflow has no migration heads")
        if initialize and not current:
            if inspect(connection).get_table_names():
                raise ValueError("Refusing to initialize a nonempty unrelated database")
        elif current != expected:
            raise ValueError("Metadata schema differs; initialize or migrate explicitly before starting")
    if initialize and not current:
        db.initdb()
    db.check_migrations(timeout=1)
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
        if current != expected:
            raise ValueError("Database schema initialization is unresolved")
    return {"database": name, "postgresql_major": major, "migration_heads": sorted(current)}


def admin(parameters):
    from airflow.providers.fab.auth_manager.cli_commands.utils import get_application_builder
    from werkzeug.security import check_password_hash
    with get_application_builder() as builder:
        security = builder.sm
        role = security.find_role("Admin")
        if role is None:
            raise ValueError("Administrator role is missing")
        user = security.find_user(username=parameters["admin_username"])
        if user is None:
            user = security.add_user(parameters["admin_username"], "Ambari", "Administrator",
                                     parameters["admin_email"], role, parameters["admin_password"])
        if (not user or not user.active or not check_password_hash(user.password, parameters["admin_password"])
                or not any(value.name == "Admin" for value in user.roles)):
            raise ValueError("Existing administrator identity or credentials do not match")
        return {"user_id": int(user.id), "username": user.username, "role": "Admin", "active": True}


def validate_health(value):
    for name in ("metadatabase", "scheduler", "triggerer", "dag_processor"):
        record = value.get(name)
        if not isinstance(record, dict) or record.get("status") not in {"healthy", "unhealthy", None}:
            raise ValueError("Invalid Airflow subsystem observation")
        if record.get("status") != "healthy":
            raise AirflowNotReady("Airflow subsystem is not healthy")
        if name != "metadatabase":
            heartbeat = record.get("latest_" + name + "_heartbeat")
            if not isinstance(heartbeat, str):
                raise ValueError("Airflow heartbeat identity is missing")
            from datetime import datetime, timezone
            observed = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
            if observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 120:
                raise ValueError("Airflow heartbeat is stale or invalid")
    return {name: value[name] for name in ("metadatabase", "scheduler", "triggerer", "dag_processor")}


def ready(parameters):
    url = "http://" + parameters["server_host"] + ":" + parameters["api_port"]
    deadline = time.monotonic() + 90
    while True:
        try:
            auth = json_http(url + "/auth/token", {"username": parameters["admin_username"], "password": parameters["admin_password"]})
            token = auth.get("access_token")
            if not isinstance(token, str) or not token:
                raise ValueError("Airflow authentication produced no access token")
            headers = {"Authorization": "Bearer " + token}
            health = validate_health(json_http(url + "/api/v2/monitor/health", headers=headers))
            return url, headers, health
        except urllib.error.HTTPError as error:
            if error.code not in {502, 503, 504}:
                raise
        except (urllib.error.URLError, TimeoutError, AirflowNotReady):
            pass
        if time.monotonic() >= deadline:
            raise AirflowNotReady("Airflow did not become ready within the startup allowance")
        time.sleep(2)


def check_dag(url, headers, execution):
    dag_id = "ambari_mpack_health"
    base = url + "/api/v2/dags/" + dag_id
    deadline = time.monotonic() + 180
    while True:
        try:
            dag = json_http(base, headers=headers)
            break
        except urllib.error.HTTPError as error:
            if error.code != 404 or time.monotonic() >= deadline:
                raise
            time.sleep(2)
    if dag.get("dag_id") != dag_id or dag.get("is_paused") is not False:
        raise ValueError("The managed health DAG is missing or paused")
    run_id = "ambari_" + execution
    try:
        submitted = json_http(base + "/dagRuns", {"dag_run_id": run_id, "logical_date": None,
                                                 "conf": {"execution_id": execution}}, headers)
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise
        submitted = json_http(base + "/dagRuns/" + run_id, headers=headers)
    except (urllib.error.URLError, TimeoutError):
        # The Server may have accepted the run before the client lost its response.
        submitted = json_http(base + "/dagRuns/" + run_id, headers=headers)
    if (submitted.get("dag_run_id") != run_id or submitted.get("dag_id") != dag_id
            or submitted.get("conf", {}).get("execution_id") != execution):
        raise ValueError("Airflow accepted a foreign DAG run")
    while True:
        current = json_http(base + "/dagRuns/" + run_id, headers=headers)
        if current.get("dag_run_id") != run_id or current.get("dag_id") != dag_id or current.get("conf", {}).get("execution_id") != execution:
            raise ValueError("Foreign DAG run observation")
        if current.get("state") == "success":
            break
        if current.get("state") not in {"queued", "running"} or time.monotonic() >= deadline:
            raise RuntimeError("Health DAG execution failed or remains unresolved")
        time.sleep(2)
    task = json_http(base + "/dagRuns/" + run_id + "/taskInstances/verify_execution", headers=headers)
    if task.get("task_id") != "verify_execution" or task.get("dag_run_id") != run_id or task.get("state") != "success":
        raise ValueError("Health task did not complete for this run")
    xcom = json_http(base + "/dagRuns/" + run_id + "/taskInstances/verify_execution/xcomEntries/return_value?deserialize=true", headers=headers)
    returned = xcom.get("value")
    if (xcom.get("run_id") != run_id or xcom.get("dag_id") != dag_id or xcom.get("task_id") != "verify_execution"
            or xcom.get("key") != "return_value" or not isinstance(returned, dict)
            or any(type(returned.get(key)) is not int for key in ("schema_version", "sum", "rows"))
            or returned != {
                "schema_version": 1, "execution_id": execution, "sum": 45, "rows": 10}):
        raise ValueError("Health DAG returned an invalid or foreign result")
    return {"dag_id": dag_id, "dag_run_id": run_id, "task_id": "verify_execution", "state": "success", "result": xcom["value"]}


def execute(request):
    observed = {"software": version()}
    parameters, action = request["parameters"], request["action"]
    if action == "version":
        return observed
    observed["database"] = database(parameters, initialize=action == "initialize_database")
    if action == "create_admin":
        observed["administrator"] = admin(parameters)
    elif action == "check":
        url, headers, observed["health"] = ready(parameters)
        observed["dag"] = check_dag(url, headers, request["execution_id"])
    elif action not in {"initialize_database", "database"}:
        raise ValueError("Unsupported Airflow application action")
    return observed


if __name__ == "__main__":
    main(execute)
