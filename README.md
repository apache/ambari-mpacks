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

English | [简体中文](README.zh-CN.md)

This repository holds independently versioned third-party management packs for
Apache Ambari. It contains service definitions, configuration templates, and
runtime installers; the `ambari-mpack` authoring and HTTP client tool lives in
Ambari core. A pack describes how Ambari manages a service. Importing a pack
does **not** install that service on any host.

## Scope And Compatibility

The current basic acceptance target is Rocky Linux 8 on aarch64 with systemd.
Ubuntu definitions are retained but were not exercised in the current acceptance
run. The component READMEs and [acceptance records](docs/five-component-implementation.md)
describe tested versions, host prerequisites, topology limits, and remaining
security gaps. These basic tests are not a production or HA certification.

The complete store contains one shared package and ten service packages:

| Package | Role and important prerequisite | Details |
| --- | --- | --- |
| `generic-base` | Shared definitions used by the service packs | [Package](mpacks/generic-base/) |
| `nginx` | OS-managed Nginx, without Hadoop or stack-select | [Package](mpacks/nginx/) |
| `postgresql` | OS-managed PostgreSQL, without Hadoop or stack-select | [Package](mpacks/postgresql/) |
| `kyuubi` | Extends the BIGTOP Spark, Hadoop, and ZooKeeper environment | [README](mpacks/kyuubi/README.md) |
| `airflow` | Isolated Python environment and an external PostgreSQL 14-18 database | [README](mpacks/airflow/README.md) |
| `celeborn` | Pinned official binary; basic single-master topology | [README](mpacks/celeborn/README.md) |
| `dolphinscheduler` | Service-specific runtime and configuration | [README](mpacks/dolphinscheduler/README.md) |
| `trino` | Service-specific runtime and configuration | [README](mpacks/trino/README.md) |
| `doris` | Service-specific runtime and configuration | [README](mpacks/doris/README.md) |
| `elasticsearch` | Service-specific runtime and configuration | [README](mpacks/elasticsearch/README.md) |
| `minio` | Fixed source build, not the earlier definition-only draft | [README](mpacks/minio/README.md) |

`release.json` is the authoritative index of package paths and exact management
definition versions. These versions are **not** observations of installed host
software. `profiles/infrastructure.json` selects only `generic-base`, `nginx`,
and `postgresql` when a smaller bundle is needed. `tooling.lock` records the
compatible authoring tool and manifest schema versions.

## Build A Store Bundle

Use Python 3.10 or newer in an isolated environment and install the compatible
`ambari-mpack` tool from an Ambari core checkout. Check `tooling.lock` before
choosing a tool version. With a virtual environment already activated:

```sh
python3 -m pip install /path/to/ambari/dev-support/mpack
ambari-mpack --help
```

From this repository root, validate a pack and build all versions selected by
`release.json`:

```sh
ambari-mpack --json validate mpacks/nginx
ambari-mpack --json build --all --repository . --output dist --bundle mpackstore
```

The build produces individually versioned archives under `dist/` and the
transport bundle `dist/mpackstore.bundle.tar.gz`. Keep the bundle intact for
distribution. To build only the infrastructure profile, replace `--all` with
`--profile infrastructure` and choose a distinct bundle name. To select specific
packs, use `--packs generic-base,nginx,postgresql` instead. Include every
required dependency in a bundle unless it is already imported on the target
Server. These selection modes read the same exact versions from `release.json`;
building a bundle does not contact an Ambari Server.

## Import And Select Services

Use an Ambari Server that supports the HTTP Management Packs API. In the Ambari
UI, open **Management Packs**, upload `dist/mpackstore.bundle.tar.gz`, and choose
**Import Packages**. Import registers the complete store without enabling
definitions or running package hooks. Then open **Available Services**, select
the desired services, and choose a new cluster or a compatible existing cluster.
The Server resolves required provider packages and extension bindings; selecting
one service does not deploy every service in the bundle.

The equivalent HTTP-only CLI import is:

```sh
ambari-mpack --server "$AMBARI_SERVER_URL" import dist/mpackstore.bundle.tar.gz
ambari-mpack --server "$AMBARI_SERVER_URL" services
```

Set `AMBARI_SERVER_URL` to the target server before running these commands. For
HTTPS with a private CA, pass `--ca-file` to the CLI. The CLI prompts for the
Ambari password in an interactive terminal; do not put it
in a command line or repository file. For automation, provide `AMBARI_PASSWORD`
through a protected environment or secret store. The import command waits for
the operation by default. Keep its exact operation ID and inspect it with
`ambari-mpack --server "$AMBARI_SERVER_URL" operations show OPERATION_ID` if
diagnosis is needed. An interrupted submission can be resumed with `operations
resume SUBMISSION_ID`; do not infer completion from upload success alone.

## Configuration, Updates, And Recovery

The [configuration file guide](docs/content-configuration.md) covers the full
content editors for all ten services and migration from scalar values. Existing
saved content is not silently regenerated from package defaults. An imported
newer package does not automatically replace active definitions or upgrade host
software; activation and deployment are separate operations. Publish a new
package version and update `release.json` when definitions change, rather than
replacing an existing versioned archive.

Package hooks that execute during online activation must declare
`scope: "DEFINITIONS"` and respect their package boundary. This declaration is
not a sandbox for arbitrary code. The PostgreSQL reference's BACKUP creates a
verified, operation-associated archive; RESTORE requires an explicit isolated
target and will not overwrite the source database. Automatic failover,
multi-instance identity, and arbitrary frontend plugins are not provided.

This repository's commands do not directly modify the Ambari Server filesystem
or database. Configure runtime software sources through Ambari repository
records and use authoritative operations and service checks to verify results.

## Repository Guide

- `mpacks/`: versioned package definitions and component-specific READMEs.
- `shared/`: common runtime helpers included by declared package inputs.
- `release.json`, `profiles/`, `tooling.lock`: release selection and tool contract.
- `docs/content-configuration.md`: configuration editing and migration.
- `docs/component-expansion-results.md` and
  `docs/five-component-implementation.md`: acceptance evidence and limitations.
- `docs/component-expansion-plan.md`: possible future services, including
  SeaTunnel, Superset, and an Iceberg catalog service.

Contributors can run `python3 -m unittest discover -s tests -v` for this
repository's focused tests. Adding a service must not duplicate an existing
BIGTOP provider as a side effect.
