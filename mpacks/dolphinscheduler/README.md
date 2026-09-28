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

# DolphinScheduler 3.1.9 Basic Package

This pack adds a single-host pseudo-cluster to BIGTOP/3.3.0. One Ambari
component supervises DolphinScheduler's master, worker, API and alert servers
as four separate foreground systemd processes. It requires an empty dedicated
PostgreSQL 14-18 database, external ZooKeeper, and Java 11 or 17. The upstream
standalone mode is deliberately not used: its default in-memory H2 metadata
database is cleared on restart, and it starts a testing ZooKeeper server.

INSTALL downloads the official 3.1.9 binary or reads an operator-preloaded
`/var/cache/ambari-mpacks/dolphinscheduler-3.1.9.tar.gz`. Both paths enforce
the official SHA-512. An empty metadata schema is initialized once and marked
as owned; a nonempty foreign schema or unexpected version is rejected. A failed
owned initialization can be retried without deleting the database. The
upstream default `admin/dolphinscheduler123` credential is replaced before
START, then verified through a typed PostgreSQL row observation. Later runs
verify that administrator identity instead of resetting a changed account.

The API, master and worker are checked through DolphinScheduler's JSON login
and registry APIs, with exact assigned host identity; the four systemd units
must also be active. The first release does not run a real scheduled workflow
as part of SERVICE_CHECK. Worker auto-creation of Linux tenants and passwordless
sudo are disabled; only workflows compatible with the dedicated service user
are in scope. No HA, schema upgrade, or external task dependency installation
is implied by this management definition.

DolphinScheduler 3.1.9 itself stores user passwords as unsalted MD5. Keep the
initial HTTP UI on a trusted network and assess this upstream security limit
before production use. Runtime acceptance is pending. Stopping or retiring the
pack does not delete PostgreSQL metadata or workflow files.
