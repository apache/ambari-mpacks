<!--
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
-->

# Apache Airflow Basic Package

Airflow 3.3.2, Python 3.11, Rocky 8, GENERIC/1.0. One AIRFLOW_SERVER component
supervises API server, scheduler, DAG processor and triggerer under systemd.
LocalExecutor is fixed; Celery, HA and automated schema upgrades are not included.

Import the store, select Apache Airflow, assign one host and supply a dedicated
PostgreSQL 14-18 database/user/password and administrator credentials/email.
The server hostname derives from the assigned component unless explicitly set.
The existing PostgreSQL 10 reference package is not an Airflow prerequisite.
Python 3.11 packages must be available from the host's configured Rocky repository.

INSTALL creates a separate environment under /opt/ambari-mpacks/airflow/3.3.2,
verifies the pinned upstream constraints, prepares protected configuration and
initializes only an empty dedicated database. Existing current schemas are
verified, never automatically upgraded. An unrelated/nonempty or old schema
is rejected. Administrator provisioning verifies the existing identity and
password rather than resetting an existing account. INITIALIZE_DATABASE and
CREATE_ADMIN remain available for explicit recovery. START verifies migrations
without running them. Failed owned pip installations can be retried; unowned
environments are not overwritten. Internet access to PyPI and the pinned
constraints source is required for first installation.

The UI quick link opens port 8085 by default. Passwords are marked PASSWORD in
Ambari and are excluded from structured observations. Runtime secrets are retained
under /etc/airflow/ambari/secrets.json, root-only; application config is readable
only by the airflow account. Preserve these secrets together with the metadata
database for recovery. This basic package uses FAB database authentication.

SERVICE_CHECK validates database/schema identity and all subsystem heartbeats,
then runs the owned, unscheduled ambari_mpack_health DAG. It verifies the exact
DAG-run/task identities and the native XCom result (sum 45, count 10 and the
current execution UUID). Diagnostic output does not establish success. DAG-run
history is retained. User DAGs live in /var/lib/airflow/dags and are not removed
when definitions are retired. STOP is explicit and does not delete data.

See docs/component-expansion-results.md for executed checks and limits.
