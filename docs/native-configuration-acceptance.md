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

# Native Configuration Acceptance

Date: 2026-09-28. This deliverable follows the request to replace minimal
installation-only configuration forms with practical native configuration
management. The implementation uses the service's own files and metadata;
the am-pro Kyuubi implementation was a reference, not a copied dependency.

## Result

Eight packs now provide Basic Settings and Native Settings tabs, complete-file
editors where applicable, and custom native properties. Save/restart/application
and restoration were exercised on the running Rocky 8 ARM64 acceptance clusters.
The UI fixes preserve custom-property entry when all predefined fields are
themed, honor adding_forbidden, and expose defaults for newly introduced
configuration types on the current configuration version.

| Pack | Final definition | Final service-check request / task |
| --- | --- | --- |
| Kyuubi | 1.0.0.11 | 274 / 556 |
| Airflow | 1.0.0.6 | 257 / 535 |
| Celeborn | 1.0.0.2 | 277 / 561 |
| DolphinScheduler | 1.0.0.5 | 271 / 551 |
| Trino | 1.0.0.4 | 259 / 537 |
| Doris | 1.0.0.7 | 262 / 542 |
| Elasticsearch | 1.0.0.5 | 265 / 545 |
| MinIO | 1.0.0.5 | 268 / 548 |

All eight final checks reported COMPLETED and APPLIED with a matching task ID,
canonical execution UUID and definition snapshot:
`3f61f0944eab2ea5c74edf0a163c3811d63e7f8a3aed37d271ba82cc8d68bd62`.

Elasticsearch and MinIO run in `mpack_five_generic_20260928`; the other BIGTOP
services run in `mpack_kyuubi`. Airflow acceptance uses
`mpack_airflow_clean_20260926`. The older stopped Airflow fixture was not
started for this acceptance.

## Browser And Runtime Evidence

The browser visited all eight service configuration pages, checked the new
fields and complete-file editors, and verified that custom-property categories
exist only for extensible types. Every service had a representative setting
changed through the UI and saved as a new version. Existing values were restored
through the same UI and applied again.

| Service | Change / restored value | Observation |
| --- | --- | --- |
| Kyuubi | Spark shuffle partitions 3 / 2 | Real JDBC SET query; session UUID and server operation UUID; separate execution UUID echoed by SQL |
| Trino | Added memory catalog / removed it | SQL against system.metadata.catalogs returned 1 / 0; TPCH service check remained valid |
| Doris | Slow-query threshold 6000 / 5000 ms | ADMIN SHOW FRONTEND CONFIG returned the expected Value |
| Elasticsearch | search.max_buckets 65000 / 65536; added / deleted node.attr.acceptance | Authenticated HTTPS node-settings API, stable node ID, attribute present / absent |
| MinIO | API request deadline 11s / 10s | Matching systemd service PID and its actual process environment |
| Celeborn | Worker flusher threads 3 / 2 | Typed /api/v1/conf response on the assigned worker |
| Airflow | Log level WARNING / INFO | Installed Airflow configuration API plus real health-DAG service check |
| DolphinScheduler | Master execution threads 101 / 100 | Rendered application.properties plus authenticated API and master/worker registration check |

DolphinScheduler's thread-pool size was verified at the configuration-file
boundary; this run did not introspect the JVM thread pool or submit a real
DolphinScheduler workflow. Airflow's configuration readback used the installed
configuration library; its separate service check executed the health DAG.

New-type default visibility, deleted-property preservation, history behavior,
read-only contexts and forbidden custom categories also have frontend regression
coverage. The live fixture's initial new types were seeded through the ordinary
configuration API with existing values preserved; no database tables were edited.

An initial Kyuubi check (request 224) failed during listener startup. The final
pack adds a bounded listener wait before the existing identity-checked SQL
operation. Subsequent checks, including the final immediate post-start check,
passed. Draft definitions used during acceptance remain immutable; corrected
definitions were imported at new version numbers.

## Automated Verification

Commands executed successfully:

- `python3 -m unittest discover -s tests`: 77 tests passed on macOS.
- `docker exec -e TMPDIR=/var/lib ambari-mpack-five-bigtop-20260928 /usr/bin/python3.11 -m unittest discover -s /mpacks/tests`: 77 tests passed on Rocky 8. The pinned Airflow constraints fixture was copied into the container before the final run; no final skips.
- `npm test` in ambari-web/latest: 251 files and 1,409 tests passed.
- `npm run build`: TypeScript and Vite production build passed. Existing Sass deprecation and bundle-size warnings remain.
- Two complete eleven-pack store builds compared byte-for-byte using `cmp`.
- Final configuration/Theme metadata coverage validates each declared property
  placement, dependencies, and the service-level Theme declaration.

The rendering tests cover managed-key conflicts, newline/NUL rejection, Unicode
property escaping, literal environment exports, invalid XML/JVM input, duplicate
or traversing catalog names, catalog removal, and retry after interrupted writes.

## Local Artifacts

Evidence, screenshots, immutable draft archives and final archives:
`~/.local/share/ambari-mpack-acceptance/native-config-20260928/`.

Final store:
`final-b/mpackstore.bundle.tar.gz`

SHA-256:
`8f2eb9fba390df762f97c1e4cd3b010c01404f65c8a26c4238e5a595a5b2dbfb`

Key evidence files include `browser.json`, `final-checks.json`,
`*-runtime-changed.json`, `*-runtime-restored.json` and
`*-ui-restore.json`. Private cluster configuration evidence remains outside Git.

The existing prebuilt cluster was reused. Only frontend assets were replaced;
management definitions were updated through the mpack API. No new Ambari RPM
was built. See [the configuration guide](native-configuration.md) for supported
files and the retained topology/authentication limits.

Code and this conclusion are committed locally. The mpack store is not pushed.
