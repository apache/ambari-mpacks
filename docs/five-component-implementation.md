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

# Five-Component Implementation Record

Date: 2026-09-28. The user selected installable, non-HA first releases for
DolphinScheduler, Trino, Doris, Elasticsearch and MinIO. All source checkouts
were shallow-cloned through the local HTTP proxy at `127.0.0.1:7890` into
separate `/Users/jialiang/PRJS` directories. They remain clean and outside the
mpack source repository. No third-party binary is committed to this repository.

| Pack | Source checkout | Exact source commit | Runtime provenance |
| --- | --- | --- | --- |
| DolphinScheduler 3.1.9 | `dolphinscheduler-3.1.9` | `400ed9147a3fd89c361e1c2bd53c94cb1e5c9b65` | Official ASF archive, SHA-512 `b09e7a11245dc9db8be8c0600857f077c4287380a676577bf3157e98ef2940ab5164d954e30596503dd0a52ab5866d5a7cd4edc88b2f04bdc3407ca441fbd764` |
| Trino 483 | `trino-483` | `50b0b50b75abd47f830b7805ee1b51716eb4065e` | GitHub release archive, SHA-512 `5b6920dcb807608e13bb0f2d6d062233ffafe627d035ac37c37da28dbfd0933f10a37871505247ef65e1f973f503b341f9038d0a52773e0ceb0dcf6d037fb6ee` |
| Doris 4.1.4 | `doris-4.1.4` | `ad35a140c7fd0b842f18c23300bac581f7d04326` | Official ARM64 distribution, SHA-512 `15ba9dbb76b60b54360cd8580e3433cad0fa85e216512da72afc3559eff2eac708dc839f1634e2415d4b54a3abe0722d98471205b9fd52e12380d823ee144dbc` |
| Elasticsearch 9.5.4 | `elasticsearch-9.5.4` | `9170df19cae1adb107b7b489b4d82dec66d7a337` | Official Linux/ARM64 distribution, SHA-512 `51d42530da01deb81b538c2d4c27f6f023f1d11d9415865b5dbabab7d6699831f8fc8aaffb1f73d2d5915a212d613d9ee0e44debce361a25a7e4b59663b1701c` |
| MinIO release 2025-10-15 | `minio-2025-10-15` | `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a` | Pinned source SHA-512 `9b4ff0a68f615a1fd646b0ef0125930f71dfa6afbba4a5eb819a5d5f016c7363fefb9c6d45e0afc4742ffb6c1bec5987c471c3ed2bf0a32f68749546b9a9144a`; Go 1.24.8 Linux/ARM64 build SHA-256 `36a65e472ca0a0a3a209ca0ab10d1966e8e089d92b7466a7e45df8d1e4d6708f` |

The accepted definitions are DolphinScheduler `1.0.0.3`, Trino `1.0.0.2`,
Doris `1.0.0.5`, Elasticsearch `1.0.0.3` and MinIO `1.0.0.3` in
`release.json`. Earlier imported versions and their failed tasks were retained;
no published archive was overwritten. Trino, Doris
and DolphinScheduler target BIGTOP/3.3.0; Elasticsearch and MinIO target
GENERIC/1.0. Import alone remains metadata-only. Each service requires the
operator to choose it in Available Services, supply its explicit prerequisites
and credentials, and deploy through the normal Ambari wizard. The existing six
package versions and built archive digests were not changed.

## Basic Management Contracts

- DolphinScheduler: one host with four supervised processes, external
  PostgreSQL and ZooKeeper, owned empty-schema initialization, verified admin
  replacement and authenticated master/worker registry observation. The
  upstream standalone H2/testing-ZooKeeper path is excluded.
- Trino: one coordinator and optional workers, Java 25, stable node identities,
  native node-info observation, and an operation-linked TPCH query through the
  structured statement API. Production catalogs are not installed implicitly.
- Doris: one FE and one BE, co-located or separate, verified 4.35 GB ARM64
  archive, protected FE identity, exact BE SQL registration, and an
  operation-owned table write/read/drop check.
- Elasticsearch: one authenticated HTTPS node with a hostname-bound retained
  certificate, explicit elastic password bootstrap, native cluster health and
  operation-owned index/document write/read/delete. The vendor binary is
  downloaded by the host rather than redistributed in this pack.
- MinIO: one persistent server and embedded console, explicitly supplied root
  credentials, pinned source and Go toolchain, exact binary digests, and a
  MinIO Go SDK object write/read/delete check with cleanup state. The source is
  AGPL-3.0; its binary is not redistributed inside the Apache-licensed pack.

The new archive installer rejects traversal, ambiguous entries, foreign links,
unsupported host architectures and wrong hashes. Concurrent component installs
on one host share a process lock and publish one verified runtime. Existing
Airflow/Celeborn shared helper bytes remain pinned to their original versions.

## Executed Verification

- The local and Rocky 8 Python 3.11 suites passed 66 tests with no skips after the pinned
  Airflow constraints fixture was provided. New tests exercise structured
  identities, incorrect results, credentials, cleanup failure, and concurrent
  installation. All new Python files compiled; `go vet` passed for the MinIO
  SDK checker.
- The four downloaded official binary archives matched their published or
  independently recorded SHA-512 values. The safe extractor processed actual
  Trino, DolphinScheduler, Doris and Elasticsearch distributions (6938, 3692,
  1759 and 1963 entries respectively). Doris expanded to about 6.8 GB.
- MinIO source from the Git checkout and the pinned source archive independently
  produced the same Linux/ARM64 server binary digest. The SDK checker built to
  identical bytes from both source locations and after relocation. A separate
  macOS build ran against an isolated local MinIO process: an execution-owned
  S3 object was written, read with the expected SHA-256, and cleaned up. Its
  typed result reported `APPLIED` and `cleanup=true`; the process was stopped.
- Two separate final 11-package bundle builds compared byte-for-byte, SHA-256
  `3e362d24021f1af09763fa27e3c04fcb3878b0bf11df6e4e2360403edb6cbe04`.
  The bundles and large upstream artifacts are retained outside Git under
  `~/.local/share/ambari-mpack-acceptance/new-components-20260928`.

## Live Cluster Acceptance

After the user authorized deployment, the existing disposable Docker cluster
was resumed and two isolated Rocky 8 ARM64 Agents were added from its verified
prebuilt image. Ambari was not rebuilt into a new RPM. Server class fixes and
frontend assets were replaced in place, and corrected mpack definitions were
published with new versions. The native API imported the eleven-package bundle
in operation `9ebed707-1609-4e05-9ff9-3cb18a4cad6e`; all five services were
separately enabled and installed through normal Ambari tasks.

| Service | Install evidence | Final stop / start / check requests | Native check result |
| --- | --- | --- | --- |
| Trino | 144 / task 354 | 188 / 189 / 190 | Task 457, stable node UUID, exact query ID, TPCH nation count 25 |
| DolphinScheduler | 153 / task 370 | 191 / 192 / 193 | Task 460, authenticated API, master and worker registration; PostgreSQL 18 schema 3.1.9 |
| Doris | 152 / tasks 368-369 | 194 / 195 / 196 | Task 465, exact FE/BE inventory, one inserted/read row with sum 42, owned database cleanup |
| Elasticsearch | 142 / task 352 | 197 / 198 / 199 | Task 468, authenticated HTTPS, green cluster, exact document UUID, owned index cleanup |
| MinIO | 169 / task 405 | 200 / 201 / 202 | Task 471, exact source/binary identities, S3 object digest and cleanup |

The final checks used definition snapshot
`f79d327dadae1e3b3da70026d88e64d320af9caf26359cc0e2a157d412072d50`.
Every successful task had a matching task ID, execution UUID and `APPLIED`
observation. The embedded `source.json` labels remain the immutable build-time
`IMPLEMENTED_PENDING_ACCEPTANCE` metadata; this document records the later
acceptance of the exact versions above.

Live failures exposed and corrected the following issues: Rocky OpenSSL
configuration duplicated certificate extensions; standard JDK aliases were
incorrectly rejected; Doris persistent directories and nested TLS configuration
were treated as immutable resource conflicts; Agent Python paths polluted the
system observer; Go builds incorrectly depended on a login HOME; and initial
credential setup could remain unresolved despite an active process. Trino now
waits for typed node readiness before its query check. Failed requests 143,
146, 149, 155, 156, 158, 160, 168, 171, 173 and 187 remain diagnostic evidence.

Two Ambari Server caches also required correction. Command ordering now follows
the current immutable definition view, including rollback; Doris FE starts
before BE and stops after BE in separate native stages. Configuration ownership
now refreshes with that view, so newly added services receive service config
versions. Missing initial config versions were repaired through the normal
configuration API, without direct database edits. Java regression: 51 tests
passed, including the cluster and role-order suites.

Authenticated browser checks covered summary navigation across the seven
imported services and all five new Configs pages. An old open browser session
recovered after refresh. The generic Summary now keeps declared master names
visible during partial host reads. Configs shows all defined properties,
expands the ordinary fallback layout, and does not show a missing-layout warning
for intentionally unthemed services. Current modeled property counts are 8
for Elasticsearch, 8 for MinIO, 12 for DolphinScheduler, 7 for Trino and 15 for
Doris; these are basic operational parameters, not every upstream native knob.
The browser saved Elasticsearch heap size 2G as a new configuration version;
after native stop/start requests 203/204, the JVM API reported 2147483648 bytes.
The baseline is restored to 1G after this check. Full frontend regression passed
1395 tests; focused fallback tests and the production build also passed.

## Acceptance Limits

Doris's official BE launcher rejects the Docker VM's enabled swap. The isolated
BE unit used a test-only `SKIP_CHECK_ULIMIT=true` override with an explicit
1048576 file limit; the kernel map count was 2000000. This override is not in
the mpack. Production hosts must disable swap and satisfy the upstream limits.
Deployment used the native APIs; the complete interactive installation wizard
was not re-executed. The accepted configuration surface is the declared basic
properties, not arbitrary upstream advanced configuration.

The first releases deliberately omit HA, upgrades and distributed MinIO
storage. DolphinScheduler 3.1.9 retains upstream unsalted-MD5 user password
storage, has no passwordless-sudo tenant execution, and has not run a scheduled
workflow in SERVICE_CHECK. Trino lacks production catalogs and authentication.
Doris FE briefly has its upstream empty root password before the supervised
bootstrap completes and its MySQL-compatible port is not TLS-enabled in this
basic topology. Elasticsearch's self-signed certificate must be distributed to
clients. Keep these basic deployments on trusted networks and assess the
upstream license and security requirements before production use.
