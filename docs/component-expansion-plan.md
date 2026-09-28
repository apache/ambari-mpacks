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

# Component Expansion Proposal

Update 2026-09-28: the later request superseded the deferred MinIO decision
below. MinIO now has a source-built installable package in `release.json`;
DolphinScheduler, Trino, Doris and Elasticsearch were also added. See
`five-component-implementation.md` for their acceptance status. The original
2026-09-26 decision and evidence remain below as historical context.

Date: 2026-09-26. The user selected a basic first release rather than HA, and
explicitly deferred MinIO installation. Airflow and Celeborn are now selected in
`release.json`; MinIO remains an excluded definition draft. See the separate
results document for actual verification. Additional components below are
recommendations and have not been authorized for implementation.

## Requested Packages

| Package | Purpose | Proposed components | Initial destination |
| --- | --- | --- | --- |
| Airflow | Scheduled data pipelines and DAG orchestration | API server, scheduler, DAG processor, triggerer; optional worker only with an explicitly supported executor | GENERIC/1.0, with an external supported metadata database |
| MinIO | S3-compatible object storage for data lakes and applications | Server; console is part of the server process | GENERIC/1.0 |
| Celeborn | Remote shuffle service for Spark/Flink | Master and worker; engine-specific client libraries are separately selected | BIGTOP/3.3.0 initially |

Keep definition versions separate from installed software versions. For the
first implementation, prefer a single supported topology per package rather
than controls that advertise unimplemented HA, recovery or upgrade paths.
HA and Airflow CeleryExecutor are outside this first release.

### Airflow

- Airflow's official release API returned 3.3.2 during investigation. Select
  and pin the final version, Python ABI and upstream constraints together.
- Use an isolated application Python environment. Never install Airflow into
  the Ambari Agent environment or the OS platform Python environment.
- Current Airflow documentation lists Python 3.10 through 3.14 and PostgreSQL
  14 through 18. The store's currently exercised PostgreSQL 10.23 is not a
  suitable implicit dependency. Require a compatible external database or a
  separately implemented modern PostgreSQL package.
- LocalExecutor is a reasonable initial topology. CeleryExecutor additionally
  needs an explicit broker, worker placement, shared configuration and secret
  distribution. It must not be a cosmetic executor dropdown.
- Database provisioning, schema migration and administrator provisioning are
  separate operations. Startup must not silently migrate a production schema.
  Verify the actual database/schema state after a migration command.
- Handle database credentials, Fernet keys, JWT and API secrets as sensitive
  configuration. Do not echo them in structured task observations or command
  diagnostics. Existing DAG files and metadata survive definition retirement.
- Check typed API health, scheduler/processor heartbeat and a real test DAG
  with exact DAG-run/task-run identities. An HTTP 200 alone is insufficient.

### MinIO

- The official community README now states that new releases are source-only;
  legacy binaries remain available but are not maintained. The latest release
  API returned `RELEASE.2025-10-15T17-29-55Z` with no binary assets.
- Decide between a pinned source build packaged as an RPM and an existing
  operator-provided RPM/image. Do not silently substitute a historical binary
  or an unpinned `latest` image. The user chose to defer this selection and retain
  only the non-installable MinIO definition draft.
- Treat the S3 endpoint and console endpoint separately. Preserve data paths;
  stop, uninstall definitions and upgrade must not remove buckets or objects.
- Root credentials must be explicitly supplied through protected config. Do
  not ship working default credentials. Separate TLS, region and data-directory
  validation from credential validation.
- A meaningful service check uses an S3 SDK to create an operation-owned object,
  read it back and compare its digest, then remove only the owned test resource.
  Failed cleanup remains visible. Readiness endpoints supplement this check.
- Distributed erasure storage needs an explicit endpoint set and disk topology.
  Do not let adding an Ambari host implicitly expand or reformat a deployment.

### Celeborn

- Official release 0.7.0 is available as a binary distribution:
  `https://archive.apache.org/dist/celeborn/celeborn-0.7.0/apache-celeborn-0.7.0-bin.tgz`.
- Published SHA-512:
  `58e9bac129e1e817c3d97d69dbbe30baeddc07ecf7e109bda3acdb8b7a8d55380aec663d7c5862b2b770c8c120b78ffc136dde80e6dfe0d6e0519d0815c4973d`.
  The binary was downloaded and checked against this digest. Runtime evidence is
  recorded in the component expansion results.
- Upstream supports `CELEBORN_NO_DAEMONIZE`; use foreground processes supervised
  by systemd instead of identifying processes from shell output or PID text.
- Model master and worker independently, with explicit RPC/HTTP ports, worker
  storage directories and memory limits. Keep storage outside application roots.
- Single-master and Ratis HA are different deployment contracts. HA needs exact
  node IDs, peer endpoints, persistent Ratis storage and quorum-safe operations.
- Spark/Flink client selection must match the engine and Scala binary version.
  Installing a Celeborn server does not automatically prove Spark/Flink uses it.
  Do not overwrite engine jars or global configuration during pack import.
- Acceptance must include worker registration and a real shuffle job with exact
  engine job/application and Celeborn observations, plus restart/recovery cases.

## Common User Flow And Release Gates

1. Build and import the complete store bundle. Import must remain free of host
   installation, schema migration, service activation and engine configuration.
2. Select a service and compatible destination in the catalog. Describe external
   prerequisites and obtain configuration through the existing deployment wizard.
3. Validate credentials without echoing them, occupied ports, supported software,
   data-path ownership and topology before mutation.
4. Install verified artifacts, configure owned files, start components in the
   required order and run structured service checks. Provide UI links to each
   service's native console.
5. Exercise explicit stop/start, failed installation recovery, permissions,
   fresh installation, update/retirement protections and browser refresh before
   describing a package as verified. Keep old snapshots and release bytes intact.

New shared helpers must be digest-locked for their consumers. Existing packages
must not change their published bytes as a side effect of adding new services.
Provide software artifacts or an explicit reproducible packaging procedure;
a metadata-only package that cannot install its runtime is not complete.

## Recommended Next Components

| Priority | Component | Value | Main acceptance concern |
| --- | --- | --- | --- |
| High | Trino | Interactive SQL across Hive/Iceberg and relational sources | Compatible JDK, catalog credentials and a real cross-source query |
| High | Apache Doris or ClickHouse | Analytical serving and interactive reporting | Choose based on query model; model replication, storage and recovery explicitly |
| High | Apache SeaTunnel | Batch/stream ingestion and data synchronization | Connector versions, checkpoints and real source-to-target data validation |
| High | Apache Superset | Dashboards and SQL exploration | Independent Python environment, metadata schema and authentication |
| Medium | Apache Fluss | Streaming storage alongside Flink | Flink compatibility, log/storage placement and recovery |
| Medium | Apache Paimon or Iceberg catalog service | Lakehouse metadata and table access | Table formats are not daemons; select an actual catalog service and exact storage contract |
| Medium | Apache NiFi | Visual ingestion and flow management | Flow persistence, sensitive properties and cluster coordination |
| Medium | Apache Pulsar | Messaging where Kafka is insufficient | Broker, BookKeeper and metadata service lifecycle complexity |
| Later | OpenMetadata or DataHub | Metadata discovery and lineage | External database/search dependencies and ingestion jobs |
| Alternative | Apache DolphinScheduler | Visual orchestration | Position as an Airflow alternative rather than requiring two schedulers |

The existing BIGTOP definitions already include Kafka, Flink, Hive, HBase,
Spark and related services. Their future extraction into standalone packages
should be a separate compatibility migration, not duplicate conflicting
providers in this expansion.

Suggested sequence after the three requested packages: Trino, one analytical
database, SeaTunnel, then Superset. This adds capabilities without requiring the
entire ecosystem to be installed at once.

## Sources Checked

- `https://github.com/apache/airflow/releases/latest`
- `https://airflow.apache.org/docs/apache-airflow/stable/installation/prerequisites.html`
- `https://github.com/minio/minio#source-only-distribution`
- `https://github.com/minio/minio/releases/latest`
- `https://github.com/apache/celeborn/releases/tag/v0.7.0`
- `https://archive.apache.org/dist/celeborn/celeborn-0.7.0/`
- Celeborn v0.7.0 `sbin/celeborn-daemon.sh`, `start-master.sh`,
  `start-worker.sh` and `conf/celeborn-defaults.conf.template`.
