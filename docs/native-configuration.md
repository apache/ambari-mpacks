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

# Native Configuration Management

This guide records the earlier scalar configuration interface. The current
interface prefers complete file content; see [Configuration File Editors](content-configuration.md).

The Kyuubi, Airflow, Celeborn, DolphinScheduler, Trino, Doris, Elasticsearch and
MinIO packs expose native configuration through Ambari. Basic settings remain
compatible with earlier releases. Service-owned configuration types travel
with each Agent task and are consumed by the runtime renderer.

## Using Configs

- **Basic Settings** contains installation paths, topology, listener ports,
  credentials and the original memory settings.
- **Native Settings** contains common application properties, with descriptions
  and numeric or boolean controls where appropriate.
- **Configuration Files** contains full logging documents, additional JVM
  options, Trino catalogs and the Airflow FAB configuration.
- **Advanced** accepts custom native properties for extensible configuration
  types. File-content types accept their single content editor. Custom
  environment settings use the separate environment type.

Save a configuration version with a note, review any advisor warnings, and
restart the affected service. Configuration saving does not itself restart a
service. The installed service's native settings, configuration history and
restart indicators remain Ambari's normal interfaces.

For an existing installation, update the management definition first, reopen
Configs and save the newly exposed defaults together with the existing values.
Do not replace existing cluster configurations wholesale with XML defaults.
The basic settings retain their names, so existing credentials, paths, ports
and topology do not require renaming. Existing custom properties are preserved.

## Managed Files

| Service | Configuration types and behavior |
| --- | --- |
| Kyuubi | `kyuubi-defaults` writes every supplied native property; `kyuubi-environment` writes literal shell exports into `kyuubi-env.sh`; `kyuubi-log4j2` writes the complete logging file. JVM options are editable. |
| Trino | `trino-config`, `trino-node`, `trino-log`, `trino-jvm` and `trino-catalogs` manage the corresponding files. Each catalog is a name-to-properties entry in the JSON editor. |
| Doris | `doris-fe` and `doris-be` overlay the pinned vendor files. Replaced keys are removed before new values are written, preserving vendor comments and version-specific defaults. |
| Elasticsearch | `elasticsearch-settings` writes YAML settings using quoted scalars and JSON-compatible arrays; `elasticsearch-jvm` writes an options fragment; `elasticsearch-log4j2` manages the complete vendor logging document. |
| DolphinScheduler | Separate master, worker, API and alert types write Spring `application.properties` overrides beside vendor YAML. The common type overlays `common.properties`. Each role has its own full Logback editor; the runtime and JVM types configure process memory and options. |
| MinIO | `minio-environment` supplies native `MINIO_*` variables to the running server through a protected runtime document. Basic credentials and listener arguments remain authoritative. |
| Airflow | `airflow-settings` uses `section.option` keys to manage `airflow.cfg`; `airflow-webserver` manages the full FAB Python configuration. |
| Celeborn | `celeborn-defaults` writes native properties; `celeborn-environment` manages additional exports; `celeborn-log4j2` manages logging. Master and worker assignments remain in basic settings. |

Common fields are a curated subset for the pinned software versions. Additional
upstream options use the custom-property editor; the package does not enumerate
every connector, plugin or future upstream option. Arbitrary user-supplied
options remain subject to the application's own validation.

## Consistency And Recovery

Configuration types are scoped to their service; unrelated cluster credentials
are not forwarded to runtime helpers. Properties are validated and escaped,
including Java property Unicode escapes. Structured action results retain
execution identity and do not echo the input configuration.

Basic topology, installation paths and service identity take precedence through
explicit conflict rejection. Heap options for Trino and Elasticsearch belong
to Basic Settings; their JVM editors accept additional options. DolphinScheduler
database and registry settings use the existing basic fields. Invalid JVM input,
malformed catalog JSON, duplicate catalog names and unsafe catalog paths fail.

Trino records its owned catalog names before writing files, allowing retry
after an interrupted write. It removes catalogs deleted from the editor and
refuses to adopt pre-existing unowned files. The TPCH catalog is retained for
the service check.

Kyuubi waits for a reachable JDBC listener before attempting the SQL service
check. A listening socket is only a prerequisite: success still requires the
real SQL result and matching session, operation and execution identities.

## Scope

These configuration improvements retain the previously accepted single-node
or small-cluster topology. HA, new authentication modes and additional runtime
dependencies require their corresponding lifecycle support. For example,
changing an arbitrary property does not provision an Airflow Celery broker,
enable Kyuubi Kerberos or distribute Elasticsearch certificates.

The complete store remains a transport bundle of management definitions.
Software artifacts continue to use their pinned upstream sources. Published
archive bytes are immutable; configuration changes ship as new definition
versions. No RPM rebuild is required for these definition updates.

Acceptance evidence and exact final versions are recorded in
[native configuration acceptance](native-configuration-acceptance.md).
