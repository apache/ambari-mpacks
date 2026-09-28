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

# Elasticsearch Basic Package

This pack manages one Elasticsearch 9.5.4 node on GENERIC/1.0. It downloads
the official Linux/ARM64 distribution directly from Elastic, or reads an
operator-preloaded `/var/cache/ambari-mpacks/elasticsearch-9.5.4.tar.gz`.
The pinned SHA-512 is checked before extraction; the vendor binary is not
redistributed in the Apache-licensed management pack. Review the license in
the upstream distribution before deployment.

The pack requires an explicit `elastic` administrator password and
`vm.max_map_count >= 262144`. CONFIGURE generates a self-signed, hostname-bound
certificate and private key, enables HTTPS and transport TLS, and provisions a
bootstrap password through Elasticsearch's keystore without reading generated
credentials from logs. START verifies the authenticated `elastic` identity and
sets the built-in user password before recording successful initialization.
The certificate and keystore must be retained with the data directory across
definition updates and recovery; distribute the certificate to trusted UI/API
clients. A replacement node hostname or password needs an explicit migration,
not a silent reconfiguration.

SERVICE_CHECK verifies the exact cluster/version, authenticated superuser,
single-node health, and an execution-owned index/document write, read and
cleanup through the native JSON API. A yellow single-node status is acceptable
because replicas are not allocated without a second node. The pack does not
expand to multiple nodes, remove indexed data on stop/retire, or migrate an
existing cluster. Live deployment acceptance remains pending.
