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

# MinIO Basic Package

The earlier non-installable draft was superseded by the user's request for a
source-built package. This pack manages one MinIO Server on GENERIC/1.0. It
uses source commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a` from the
last published community tag, `RELEASE.2025-10-15T17-29-55Z`.

Each managed host needs a Go installation capable of selecting toolchain
1.24.8, access to the pinned source archive and Go module proxy, and persistent
storage at the configured data directory. INSTALL verifies the source archive
SHA-512, builds Linux/ARM64 binaries, and rejects builds whose SHA-256 differs
from the independently reproduced digests in `source.json`. A prepopulated
`/var/cache/ambari-mpacks/minio-RELEASE.2025-10-15T17-29-55Z.tar.gz` is also
accepted only after the same digest check. The MinIO AGPL-3.0 source and binary
are not bundled in this Apache-licensed management definition.

Provide a new root user and password through protected Ambari properties; the
pack ships no working default credentials. The secret is written only to a
0600 MinIO-owned runtime file and is not published in task observations. The
single foreground server and embedded console are supervised by systemd.
Stopping or retiring a definition never deletes bucket data. A service check
uses the pinned MinIO Go SDK client to create an operation-owned bucket, write
and read an object, verify its SHA-256, and remove only that bucket and object.
The exact execution identity and cleanup outcome are structured observations.

The first release is non-HA and uses HTTP on a trusted network. TLS and
distributed erasure storage require a separate topology and security design;
do not expose these credentials over an untrusted network. Runtime acceptance
is still required before production use.
