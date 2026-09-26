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

# MinIO Definition Draft

The user requested a basic MinIO definition but explicitly deferred installation.
`definition.json` records the proposed single-node component and ports. This is
not an installable mpack and is intentionally absent from `release.json`.

No package hooks, software download, systemd installation or deployment actions
are provided. Before promotion, select a maintained source-built RPM or an
operator-provided artifact, pin its identity, implement explicit credentials and
persistent storage, and verify S3 write/read/delete using an operation-owned key.
The embedded console is not a separate daemon. HA is outside the first release.
