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

# Trino Basic Package

This pack adds Trino 483 to BIGTOP/3.3.0. Assign exactly one coordinator and
zero or more workers. The coordinator is allowed to run queries when there are
no dedicated workers. Every assigned host must have a Java 25 runtime under
the configured `java_home`; Trino 483 rejects Java 24 and earlier. The
installer downloads the official archive over HTTPS or from an operator's
prepopulated `/var/cache/ambari-mpacks/trino-483.tar.gz`. Both paths require
the exact SHA-512 in `source.json`.

INSTALL verifies the distribution and preserves its root-owned files under
`/opt/ambari-mpacks/trino/483`. CONFIGURE writes only owned paths under
`/etc/trino/ambari` and `/var/lib/trino`; the node UUID survives restarts and
definition updates. START and STOP use a foreground process supervised by
systemd. A service check observes each node's exact version, role and ACTIVE
state, then executes a real TPCH query through Trino's structured statement
protocol and verifies its query ID, FINISHED state and result.

The pack supplies only the built-in TPCH test catalog. Add production catalogs,
authentication, TLS, resource groups, and HA through a separately reviewed
configuration change; do not expose the initial HTTP port outside a trusted
network. Connector integrations with Hive, Iceberg, or other services are not
implicitly enabled by installation. A failed or unverified runtime action
remains unresolved rather than becoming a healthy service state.
