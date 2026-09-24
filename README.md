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

This independent repository contains reference definitions, not verified software
releases. Delivery is tracked in the Ambari core worktree's `docs/mpack` baseline.
The current acceptance target is Rocky Linux 8 on aarch64 with systemd.
The existing Ubuntu definitions are retained but Ubuntu deployment and testing
are excluded from this run. Nginx and PostgreSQL use operating-system packages
without Hadoop or stack-select. [Kyuubi](mpacks/kyuubi/README.md) extends the
BIGTOP environment and uses its existing Spark, Hadoop and ZooKeeper services.
Platform adaptations and new Kyuubi definitions are not yet live-verified.

Install the version-pinned `ambari-mpack` tooling published by Ambari core.
`release.json` selects the current package sources and exact management-definition
versions. Build with `ambari-mpack build --all --bundle infrastructure` and upload
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

The full store includes generic-base, nginx, postgresql and kyuubi. The
`infrastructure` profile remains the three GENERIC packages. Their Rocky
adaptation, complete Rocky repositories and Agent defaults are release `1.0.0.3`;
Kyuubi is `1.0.0.2`. Earlier imported releases are retained for provenance. Mixed-platform
imports do not bind every package to one stack: choose services for their
compatible destination through the imported service catalog.
Importing a newer store does not silently replace active definitions or upgrade
host software. The bundle contains management definitions and scripts; configured
software repositories supply the host packages.

Package hooks which execute during online activation must declare
`scope: "DEFINITIONS"` and honor the package's resource boundary. Hooks with an
omitted or `SERVER` scope can be imported but cannot execute through online
activation. This declaration does not sandbox arbitrary package code.

The PostgreSQL reference preserves source data. BACKUP produces a verified,
operation-associated archive backup; RESTORE requires an explicit isolated target
and will not overwrite a source database. Automatic failover, multi-instance
identity, and arbitrary frontend plugins are not provided.
