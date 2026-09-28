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

# Content Configuration Acceptance

Date: 2026-09-28. The user requested complete content editors for PostgreSQL
and Nginx and asked to prefer the same approach for Kyuubi and the other packs.

## Delivered Behavior

All ten services open the Configuration Files tab first. PostgreSQL exposes
postgresql.conf, pg_hba.conf and pg_ident.conf; Nginx exposes nginx.conf.
The other eight services expose their native application, environment, JVM,
logging and catalog documents where applicable. Basic Settings retains the
management inputs described in [the guide](content-configuration.md).

Current scalar configurations are proposed as editable content using their saved
values and explicit file-format metadata. Saving replaces the obsolete scalar
properties. Saved content and historical versions are preserved. Automatic
migration is skipped for scalar host-group overrides and password-typed
properties; their previous runtime representation remains supported.

## Final Versions And Checks

| Pack | Definition release | Final service-check request / task |
| --- | --- | --- |
| Nginx | 1.0.1.1 | 351 / 667 |
| PostgreSQL | 1.0.1.1 | 358 / 673 |
| Kyuubi | 1.0.1.0 | 340 / 656 |
| Trino | 1.0.1.0 | 341 / 657 |
| Doris | 1.0.1.0 | 342 / 658 |
| DolphinScheduler | 1.0.1.0 | 343 / 659 |
| Celeborn | 1.0.1.0 | 344 / 660 |
| Elasticsearch | 1.0.1.0 | 345 / 661 |
| MinIO | 1.0.1.0 | 346 / 662 |
| Airflow | 1.0.1.0 | 347 / 663 |

Every final check reported COMPLETED and a matching APPLIED runtime observation,
task ID and canonical execution UUID. They used definition snapshot
`e9e0120efaff5bc89aa280bbb07cb77fe5d44f9a3a640396a76e199752a51887`.
The final API check found all ten selected services STARTED.

The acceptance clusters are mpack_fresh_20260926 for Nginx/PostgreSQL,
mpack_five_generic_20260928 for Elasticsearch/MinIO,
mpack_airflow_clean_20260926 for Airflow, and mpack_kyuubi for the other services.
Other stopped fixtures were not started.

## Live Verification

- Browser checks saved and reopened nonempty content editors for every service.
  Converted types contained only the content property after saving.
- A Nginx location added in the UI returned HTTP 200 with the expected body
  after RELOAD. Reload verification also required the exact rendered
  configuration digest from the new workers.
- Invalid Nginx syntax was rejected in request 349. The main file digest remained
  unchanged; restoring the valid content and reloading succeeded in request 350.
- PostgreSQL work_mem changed from 4MB to 8MB through the content editor, restart
  and a native current_setting query.
- Invalid PostgreSQL content was rejected in request 355 without replacing the
  preceding working file. The original content was restored, startup succeeded
  in request 357, and work_mem returned to 4MB.
- Requests 336 and 337 verified exact API content and exact rendered Nginx file
  digests for trailing spaces and blank lines, followed by restoration.
- A definition update retained the exact Doris content values and config tags.
- Native readback after conversion preserved Kyuubi Spark settings through JDBC,
  Trino catalog inventory through SQL, Doris FE settings through SQL,
  Elasticsearch settings through HTTPS, MinIO process environment, Celeborn
  configuration through its typed API, and Airflow's installed config parser.
  DolphinScheduler application.properties and authenticated registration checks
  matched the existing baseline.

DolphinScheduler did not run a real scheduled workflow in this acceptance.
Ubuntu deployment and HA/security expansion remain outside the validated scope.
Existing OS-managed PostgreSQL/Nginx files are not automatically discovered by
the UI; the supplied defaults are installation templates.

## Tests And Deployment

- Store: `/Users/jialiang/PRJS/deploy/.venv/bin/python -m unittest discover -s tests`
  passed 88 tests.
- Rocky 8 ARM64: Python 3.11 with the pinned PyYAML test dependency passed the
  same 88 tests. The Airflow constraints fixture was present; no tests skipped.
- React: `npm test` passed 252 files and 1,417 tests. Targeted migration,
  full-content save and historical-value tests also passed.
- `npm run build` passed TypeScript and Vite production compilation; existing
  Sass deprecation and bundle-size warnings remain.
- JDK 17 compiled the two affected Server classes and the focused test class
  using the existing Surefire dependency classpath. JUnitCore executed
  PropertyValueTrimmingStrategyDefinerTest: 2 tests passed.
- Blueprint content trimming now preserves file whitespace; ordinary scalar
  and directory trimming retain their behavior.
- Two complete eleven-pack bundle builds compared byte-for-byte.

The existing prebuilt cluster was reused. Frontend assets and seven Server
class entries were replaced; all other deployed JAR entries were verified
unchanged by their ZIP CRCs. The Server was restarted and its retained clusters
were confirmed through the API. No Ambari RPM was rebuilt. Definitions were
updated through normal mpack operations with new immutable version identities.

## Local Evidence

Directory:
`~/.local/share/ambari-mpack-acceptance/content-config-20260928/`

Final bundle:
`final-c/mpackstore.bundle.tar.gz`

SHA-256:
`df8b7a7f320b895b91768b9e50aa5cb4bb7a53685b1bc3da81ca82d470ce3376`

The directory contains per-service browser screenshots and receipts,
final-state.json, validation-recovery.json, whitespace-acceptance.json,
content-preserved-across-update.json, native readbacks, and build/test logs.
Private configuration evidence and Server binaries remain outside Git.
The code and conclusion are committed locally; the store is not pushed.
