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

# Configuration File Editors

The PostgreSQL, Nginx, Kyuubi, Trino, Doris, Elasticsearch, MinIO, Airflow,
Celeborn and DolphinScheduler packs open **Configuration Files** first.
Edit complete documents in the `content` fields, save a version with a note,
and restart the service. Nginx also supports the component RELOAD command.
**Basic Settings** retains installation inputs, managed listeners, credentials
and management-operation parameters.

| Service | Main editable content |
| --- | --- |
| PostgreSQL | postgresql.conf, pg_hba.conf, pg_ident.conf |
| Nginx | nginx.conf, including user server/location/proxy directives |
| Kyuubi | kyuubi-defaults.conf, environment assignments, log4j2.properties |
| Trino | config.properties, node.properties, log.properties, jvm.config, catalog documents |
| Doris | fe.conf and be.conf; vendor startup defaults are retained where the document does not replace them |
| Elasticsearch | elasticsearch.yml, JVM options, log4j2.properties |
| MinIO | minio.env assignments |
| Airflow | airflow.cfg, webserver_config.py |
| Celeborn | celeborn-defaults.conf, environment assignments, log4j2.properties |
| DolphinScheduler | application.properties for each role, common.properties, role-specific Logback files and JVM options |

## Existing Configurations

When a type changes from individual properties to a single content field, the
current Configs page prepares a document from the currently saved values.
It uses the declared property-file-type metadata, affects only the selected
service, and leaves history unchanged. The conversion is a pending edit until
Save is selected. Existing saved content is never regenerated from package
defaults. Definitions can therefore be updated without replacing user-edited
documents.

Automatic conversion is deliberately skipped for types with existing scalar
host-group overrides or password-typed properties. Their previous scalar runtime
mode remains supported. Convert those defaults and groups together explicitly;
a complete-file override has different inheritance semantics from individual
property overrides.

The previous PostgreSQL and Nginx packs did not store their complete OS files in
Ambari. Their new documents are installation templates, not automatic filesystem
discovery. For an existing customized OS-managed instance, seed the editor with
its current files before applying content management. If the new content types
are absent, the runtime retains its legacy behavior.

## Text And Management Semantics

Properties documents retain comments, continuations, escapes and application
expressions. INI sections, YAML mappings and literal environment assignments use
their native formats. Environment content accepts NAME=value or export NAME=value;
it does not execute arbitrary shell programs. Generated exports quote values
literally. MinIO also retains its supplied document in a protected minio.env file.

File content is not trimmed by the React saver or Blueprint trimming strategy.
The renderers preserve trailing spaces and blank lines. Rendered files are
terminated by a newline when one is absent. Role-specific management defaults
are added separately; conflicting user declarations fail instead of silently
overriding managed identity or listener settings.

Nginx keeps its dedicated health include under conf.d. Retain the include in the
main configuration. After reload, the observer requires both a valid health
response and the exact configuration digest served by the new workers.

PostgreSQL templates expose explicit placeholders for the data, authentication,
identity and socket paths and the Basic Settings port. Data relocation is not
performed by editing these placeholders. The management connection uses the
postgres OS account and local peer access. PostgreSQL -C validates the candidate
configuration, and startup verifies native configuration/authentication error
views, the actual port and the loaded file paths.

## Failure And Recovery

Nginx runs nginx -t against the candidate before replacing its main file.
PostgreSQL queries its native configuration parser before replacement. The
staging directory mirrors untouched resources so relative includes resolve.

For Nginx and PostgreSQL, each file is replaced atomically with private permissions. Validation or
activation failures restore preceding files; PostgreSQL startup failure stops
the failed activation before restoring its configuration. An external concurrent
file change produces an explicit reconciliation error. Previous bytes are kept
in .ambari-before files for manual crash recovery. Multi-file replacement is not
a crash-atomic database transaction.

Elasticsearch YAML requires the OS python3-pyyaml package; its Agent configure
path ensures that dependency. Existing non-HA, authentication and runtime-version
limits remain in force. Enabling a new mode can require lifecycle support in
addition to editing its configuration.

See [the acceptance record](content-configuration-acceptance.md) for exact
versions, tests and local deployment evidence.
