<!--
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
-->

# Ambari Third-Party Management Packs

The [configuration file guide](docs/content-configuration.md) describes the
complete content editors for all ten service packs, including PostgreSQL and
Nginx, and the migration of existing scalar configuration values.

This independent repository contains management definitions and runtime installers.
Core delivery is tracked in the Ambari worktree's `docs/mpack` baseline; the
[component expansion results](docs/component-expansion-results.md) record the
Airflow and Celeborn basic acceptance scope.
The [five-component implementation record](docs/five-component-implementation.md)
tracks the newer DolphinScheduler, Trino, Doris, Elasticsearch and MinIO packs.
The current acceptance target is Rocky Linux 8 on aarch64 with systemd.
The existing Ubuntu definitions are retained but Ubuntu deployment and testing
are excluded from this run. Nginx and PostgreSQL use operating-system packages
without Hadoop or stack-select. [Kyuubi](mpacks/kyuubi/README.md) extends the
BIGTOP environment and uses its existing Spark, Hadoop and ZooKeeper services.
Airflow uses an isolated Python environment and an external PostgreSQL 14-18
database. Celeborn uses a pinned official binary with a single master topology.
MinIO now uses a fixed source build after the subsequent request superseded its
earlier non-installable draft. The five newer packs have completed basic Rocky
deployment, restart and service-check acceptance; the implementation record
lists exact versions, test evidence and the remaining topology/security limits.

Install the version-pinned `ambari-mpack` tooling published by Ambari core.
`release.json` selects the current package sources and exact management-definition
versions. Build with `ambari-mpack build --all --bundle mpackstore` and upload
with the same HTTP-only client. No command in this repository modifies the server
filesystem or database. Configure software sources through Ambari repository
records; package versions do not stand in for installed software observations.

## Distribute The Complete Store

Build all versions selected by `release.json` into one transport bundle:

```sh
ambari-mpack --json build --all --repository . --output dist --bundle mpackstore
```

Distribute `dist/mpackstore.bundle.tar.gz`. Users open Management Packs in Ambari,
upload this file and select Import Packages. Import registers the complete store
without enabling its definitions or executing package hooks. Users then choose
services from Available Services and select a new cluster or a compatible existing
cluster. Required provider packages and extension bindings are derived by the
Server. The deployment wizard receives the exact selected services; importing a
multi-service package does not deploy every service it contains.

The equivalent HTTP-only CLI import is:

```sh
ambari-mpack --server "$AMBARI_SERVER_URL" import dist/mpackstore.bundle.tar.gz
ambari-mpack --server "$AMBARI_SERVER_URL" services
```

Individual packages retain their versions and can be updated independently.

The full store includes generic-base, nginx, postgresql, kyuubi,
[airflow](mpacks/airflow/README.md), [celeborn](mpacks/celeborn/README.md),
[DolphinScheduler](mpacks/dolphinscheduler/README.md),
[Trino](mpacks/trino/README.md), [Doris](mpacks/doris/README.md),
[Elasticsearch](mpacks/elasticsearch/README.md), and
[MinIO](mpacks/minio/README.md).
`release.json` is the authoritative version index. The `infrastructure` profile
remains generic-base, nginx and postgresql. Earlier imported releases are retained
for provenance. Mixed-platform
imports do not bind every package to one stack: choose services for their
compatible destination through the imported service catalog.
Importing a newer store does not silently replace active definitions or upgrade
host software. The bundle contains management definitions and scripts. The
individual package READMEs identify host prerequisites, pinned runtime downloads
or source builds, disk requirements, and the current acceptance status.

Package hooks which execute during online activation must declare
`scope: "DEFINITIONS"` and honor the package's resource boundary. Hooks with an
omitted or `SERVER` scope can be imported but cannot execute through online
activation. This declaration does not sandbox arbitrary package code.

The PostgreSQL reference preserves source data. BACKUP produces a verified,
operation-associated archive backup; RESTORE requires an explicit isolated target
and will not overwrite a source database. Automatic failover, multi-instance
identity, and arbitrary frontend plugins are not provided.

For further additions, see the [component expansion plan](docs/component-expansion-plan.md).
SeaTunnel, Superset and an Iceberg catalog service are possible next capabilities.
Existing BIGTOP services should not acquire
duplicate providers as a side effect of these additions.
