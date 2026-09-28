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

# Apache Doris Basic Package

This pack adds Doris 4.1.4 to BIGTOP/3.3.0 with exactly one FE and one BE,
which may share a host. It uses the official ARM64 binary from the Doris
download site; its 4.35 GB archive and SHA-512 are pinned in `source.json`.
The extracted distribution occupies about 6.8 GB before metadata and data.
Each assigned host needs enough disk space, Java 17 and the configured ports.
An operator-preloaded `/var/cache/ambari-mpacks/doris-4.1.4.tar.gz` is accepted
only after the same checksum verification.

The components share one root-owned software installation on each host.
Separate writable FE and BE runtime trees contain only their own configuration,
logs and PID paths; immutable libraries stay linked to the verified archive.
FE metadata and BE storage are under `/var/lib/doris` and are never removed by
STOP or definition retirement. An empty FE metadata directory is marked before
first start; a foreign nonempty directory is rejected. After FE starts, the
pack replaces the upstream empty root password with the explicitly supplied
password and verifies authentication. BE is registered by exact host and
heartbeat port through the native MySQL-compatible protocol.

SERVICE_CHECK verifies the one FE and BE inventory, creates an operation-owned
database/table, inserts and reads a row, then removes only that owned database.
Foreign results and cleanup failure remain unresolved. The first release does
not support FE or BE replication, cloud mode, authentication over TLS, automatic
capacity expansion, schema upgrades, or recovery from lost FE metadata. Keep
the MySQL-compatible port on a trusted network; a fresh FE has an upstream
empty root password until the supervised bootstrap completes. Live deployment
acceptance remains pending.
