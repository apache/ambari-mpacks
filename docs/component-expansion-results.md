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

# Component Expansion Acceptance

Date: 2026-09-26. Scope: a basic, non-HA Airflow and Celeborn management
release on Rocky Linux 8/aarch64 with an existing disposable Ambari Server.
MinIO is a non-installable definition draft. This is not a production
certification or a claim that all supported topology combinations were tested.

## Release And Import

The complete store contains six independently versioned packages:
`generic-base/1.0.0.3`, `nginx/1.0.0.4`, `postgresql/1.0.0.5`,
`kyuubi/1.0.0.7`, `airflow/1.0.0.4`, and `celeborn/1.0.0.0`.
`mpacks/minio` has no `mpack.json` and is absent from `release.json` and the
bundle. Three separate final builds (`store-h`, `store-i`, and `store-j`) produced identical
bundle bytes. The SHA-256 is
`a3380dd672af311dfaf739d2cdc6db151d4a847bd81318de32481c7ad4d0d424`;
the Airflow archive SHA-256 is
`b4e615ff8f8352a3c0ea97e28a09b764c718d53b5b1c0cc14798ad990cb86e0c`.
Older published package versions were not rewritten.

The six-package bundle was uploaded and imported without installation hooks.
Airflow and Celeborn were then separately selected from Available Services,
enabled, and handed to Ambari deployment. Their original ENABLE operations
were `4cb93e32-c9e9-428f-88e1-c0c11a5ee856` and
`43e43670-63fe-4045-86ad-9e80e31659a5`. Airflow `1.0.0.4` was activated
as an immutable update by operation
`7baed31a-62b5-404e-90b7-9c6fe531abab`, phase `SUCCEEDED`, generation 36.
The browser catalog did not offer MinIO as an installable service.

## Runtime Observations

Airflow 3.3.2 ran in an isolated Python 3.11 environment with LocalExecutor
and external PostgreSQL 18. The first cluster, `mpack_airflow_20260926`,
completed install/start tasks 302/303 and a real service check task 304.
After an update and restart, an early check (request 121/task 312) failed and
was retained. The later check (request 122/task 313) completed after readiness
waiting and exact DAG-run reconciliation. It verified the dedicated health
DAG's XCom sum 45 and row count 10 with its execution identity.

A second host and new database tested a clean installation. Before the first
attempt, the `airflow_clean_20260926` database had zero public tables and no
`alembic_version`. Request 127/task 315 failed as `INSTALL_FAILED` with a
structured `UNRESOLVED` result; request 128 was aborted. The Agent's inherited
`PYTHONPATH` had contaminated venv dependency detection. Version `1.0.0.4`
clears Agent Python environment variables from venv/pip subprocesses and can
repair an owned but incomplete installation after verifying the exact pinned
constraints. Retrying the failed component through the normal Ambari API
completed request 129/task 317. Its structured result confirmed Airflow
3.3.2, the PostgreSQL 18 database identity, migration head
`d2f4e1b3c5a7`, and the provisioned administrator. Request 130/task 318
started all four systemd units. Request 131/task 319 completed a service check
with healthy subsystem heartbeats and the exact run
`ambari_c4419cef-1631-4fe2-a4ac-59653119f91c`; its native XCom recorded
the same execution UUID, 10 rows and sum 45. The failed requests remain
visible as failure evidence. A retry must not delete the venv or metadata
database: fix the source/dependency problem, update to a new immutable pack
release when definitions change, and retry the failed host component.
The original cluster also passed a post-update check, request 132/task 320,
under the `1.0.0.4` definition snapshot with the same native XCom invariants.

Celeborn 0.7.0 used the official binary with published SHA-512
`58e9bac129e1e817c3d97d69dbbe30baeddc07ecf7e109bda3acdb8b7a8d55380aec663d7c5862b2b770c8c120b78ffc136dde80e6dfe0d6e0519d0815c4973d`.
In `mpack_kyuubi`, Master ran on worker3 and Worker on worker4. Native install
tasks 305/306, start tasks 307/308, and service checks 309 and 314 completed.
The checks consumed machine-readable Master and Worker state, including the
exact registered worker host and RPC/push/fetch/replicate ports, rather than
interpreting log messages. A further check after the Airflow update, request
133/task 321, confirmed worker4 remained registered with ports 10001-10004.

Desktop browser checks confirmed both service summaries, components, Quick
Links, and canonical service-ID navigation. The initial 390x844 mobile check
exposed an Actions/Configs overlap. After the responsive correction, another
authenticated browser run confirmed no horizontal document overflow, separate
control bounds, an expandable Actions menu, and working Configs navigation on
both Airflow and Celeborn pages. The browser exercised those controls, not the
entire service configuration editor.

## Verification And Limits

`python -m unittest discover -s tests -v` passed 34 tests on the local
environment and 34 tests on Rocky 8 Python 3.11, with no skips after the pinned
constraints fixture was provided. Package build completed and two independent
bundle outputs compared byte-for-byte. The dedicated live requests above
confirmed both success and failed-install recovery using task-linked structured
observations. The React production build and six focused sidebar/navigation
tests passed; the complete Vitest run passed 251 files and 1393 tests. Vite
reported existing Sass deprecations and bundle-size warnings.
Deployment used the existing disposable Server and prebuilt
container image; this component run did not rebuild the Ambari RPM.

This acceptance does not cover Airflow CeleryExecutor, HA, PostgreSQL other
than version 18, schema upgrades, or arbitrary user DAGs. Celeborn HA and a
real Spark/Flink Shuffle job are not verified; server registration alone is
not evidence that an engine uses Celeborn. No MinIO installation, object I/O,
or upgrade was attempted. Ubuntu and other host platforms were not tested.
The runtime evidence is retained locally under
`~/.local/share/ambari-mpack-acceptance/expansion-20260926`; private
configuration files there are not source artifacts and must not be committed.
