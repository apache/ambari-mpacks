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

# Apache Kyuubi Reference Package

This schema-1 mpack adds KYUUBI_SERVER and KYUUBI_CLIENT to a compatible BIGTOP
stack. Import it through Ambari's mpack HTTP API or the complete mpackstore
bundle. Import does not install software or activate bindings.

## Baseline

| Input | Selected value |
| --- | --- |
| Upstream | Apache Kyuubi v1.9.4 |
| Commit | 5f48f2ef5b2532383a1e21984eec94ac451caf85 |
| Definition release | kyuubi/1.0.0.7 |
| Extension and service definition | KYUUBI/1.0 |
| Initial target | Rocky Linux 8, aarch64, BIGTOP/3.3.0 |
| Engine | Spark SQL, Scala 2.12, Spark 3.5 family |
| JDK | 17 |
| Verification | Runtime results and remaining coverage are recorded in the core acceptance ledger |

Ubuntu is outside this acceptance. Existing runtime images and compatible RPMs
are reused. The mpack contains definitions and scripts, not software binaries.
`source.json` pins the official Apache binary URL and SHA-512. In an existing
Rocky 8 builder with RPM Python bindings and `rpmbuild`, package that archive:

```sh
/usr/libexec/platform-python tools/package_kyuubi_binary.py \
  /inputs/apache-kyuubi-1.9.4-bin.tgz /outputs/kyuubi-official
```

The output directory must be new. The tool verifies the archive before building
`kyuubi_3_3_0-1.9.4-2.official.el8.noarch.rpm` and emits a JSON receipt with the
source digest, RPM header identity and RPM digest. Publish that RPM into the
repository selected by the target stack before installing the service. This
step packages existing upstream binaries and performs no source compilation.
The earlier source-built `1.el8` RPM is historical acceptance input only.

The acceptance build reuses the completed Spark 3.5.8 payload from the existing
Rocky 9 aarch64 build. An isolated Bigtop recipe verifies RPM receipts and file
digests, restores the distribution and repackages it for the Rocky 8 / 3.3.0
dependency names and paths. Spark source is not compiled. Only the core and
datanucleus packages are installed for this Kyuubi path; other Spark modes,
including SparkR, are outside this runtime validation.

## Runtime And Configuration

Existing HDFS, YARN and ZooKeeper services are required. Server components
declare host dependencies on HDFS and YARN clients. Spark is supplied by the
verified core/datanucleus RPMs: Kyuubi launches its own SQL engine and does not
require a separate Spark Thrift or History Server. This keeps the real SQL
validation within the available node memory. RPM names use the
existing stack suffix convention. Set these values to actual installed inputs:

- `kyuubi-env/package_name`: exact RPM name, initially `kyuubi_3_3_0`.
- `kyuubi-env/kyuubi_home`: initially `/usr/bigtop/3.3.0/usr/lib/kyuubi`.
- `kyuubi-env/spark_home`: compatible existing Spark distribution.
- `kyuubi-env/java_home`: JDK containing Java and its source launcher.
- `kyuubi-env/server_host`: exact Server hostname reachable from the check host.
- `kyuubi-defaults/kyuubi.ha.addresses`: ZooKeeper quorum; empty derives it from assigned hosts.

The initial implementation uses authentication NONE and one OS identity
(`kyuubi`), with engine impersonation disabled. Kerberos, LDAP, Ranger
authorization, other engines and HA failover are not advertised as verified.
YARN is the default target. `local[2]` isolates initial SQL engine validation;
it does not prove YARN integration.

## Operations And Observations

INSTALL uses Ambari's package manager and observes the exact installed RPM.
CONFIGURE renders owned files under `/etc/kyuubi/ambari`; Server configuration
also creates `ambari-kyuubi.service`, running upstream `bin/kyuubi run` as
`kyuubi`. START configures first and verifies the matching systemd job/unit.
STOP verifies the stop job. VERSION_CHECK queries the RPM database. Client
installation/configuration does not create a daemon.
The unit accepts exit status 143 from the foreground launcher on SIGTERM;
the observer still requires the matching successful stop job and inactive unit.

SERVICE_CHECK and SQL_CHECK open a real JDBC session, read the typed
`KYUUBI DESCRIBE SESSION` result, and aggregate `range(10)`. They require sum 45,
count 10 and the exact Ambari execution UUID echoed through SQL. The result
includes session UUID, server operation UUID, engine ID, driver version and
successful resource closure. A private result file separates observations from
diagnostic stdout. Missing, malformed, failed or foreign results fail the action.
Failed JDBC observations retain the execution identity, stage, exception class,
SQL state and vendor code without copying exception messages or credentials.

The pinned upstream contracts are `DescribeSession.scala`,
`KyuubiStatement.getYarnATSGuid()`, `KyuubiConnection.getEngineId()` and the
configuration/foreground-launch definitions. The operation UUID comes from the
binary Thrift handle, not a log-derived identifier.

## Updates And Verification

Publish new definitions through preview and UPDATE; never replace effective
snapshots or Agent caches directly. Verify fresh tasks use the new snapshot
without silently changing the installed RPM. Active services and dependencies
block removal. Definition uninstall preserves host software and data.

From this repository run `python -m unittest discover -s tests -v` and
`ambari-mpack --json build --all --repository . --output /absolute/new/output --bundle mpackstore`.
Use the core `docs/mpack/acceptance-results.md` for actual deployment outcomes.
Local tests and archive construction are not live acceptance.
