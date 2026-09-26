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

# Apache Celeborn Basic Package

Celeborn 0.7.0 official binary, JDK 17, Rocky 8, BIGTOP/3.3.0. Select exactly one
CELEBORN_MASTER and one or more CELEBORN_WORKER components. HA is disabled.
Hostnames derive from actual component assignments; explicit overrides must
match placement. Default RPC and HTTP ports are distinct and editable.

The official binary SHA-512 is pinned in source.json and the installer. An HTTPS
mirror may supply identical bytes. Offline operators can preseed the same archive
at /var/cache/ambari-mpacks/celeborn-0.7.0.tgz; its digest is always verified.
Installation rejects escaping/unsupported archive members, publishes a versioned
root atomically and verifies installed files and internal links on reuse. It does
not run a source build or change Spark/Flink configuration.

Master and worker use upstream foreground mode under separate systemd units.
Commands retain exact systemd job observations; STOP preserves shuffle storage.
Default storage is /var/lib/celeborn/shuffle. Startup order is Master then Worker,
and shutdown order is Worker then Master. Defaults allocate 512 MiB master heap,
512 MiB worker heap and 512 MiB worker direct memory; size these for actual load.

SERVICE_CHECK uses the official JSON API to compare Master registration with
worker host/RPC/push/fetch/replication port identities and registration/shutdown
flags. It fails on a missing, foreign or unregistered worker. The quick link
opens the Master's API. This is a basic unauthenticated service intended for a
trusted network; TLS/security and HA require a separate implementation.

A running shuffle service is not automatic engine integration. Choose a Celeborn
client matching the actual Spark/Flink and Scala binary version, distribute it
and enable its shuffle manager through the engine's normal configuration flow.
A full engine shuffle workload is a separate acceptance item, not implied by the
registration check. See docs/component-expansion-results.md for current evidence.
