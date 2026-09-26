"""
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
"""

"""Package the pinned official binary in an existing Rocky 8 RPM builder."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def digest(path, algorithm):
    result = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def package(archive, output):
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / "mpacks/kyuubi/source.json").read_text())
    if source["software_version"] != "1.9.4" or digest(archive, "sha512") != source["binary"]["sha512"]:
        raise ValueError("Archive differs from the pinned official Kyuubi distribution")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        (output / name).mkdir()
    shutil.copyfile(str(archive), str(output / "SOURCES/apache-kyuubi-1.9.4-bin.tgz"))
    with (output / "build.log").open("wb") as log:
        subprocess.run(["rpmbuild", "-bb", "--define", "_topdir " + str(output.resolve()),
                        str(root / "tools/kyuubi-official.spec")], stdout=log, stderr=log, check=True)
    artifacts = list((output / "RPMS").rglob("*.rpm"))
    if len(artifacts) != 1:
        raise RuntimeError("Packaging did not produce exactly one RPM")
    import rpm
    transaction = rpm.TransactionSet()
    try:
        with artifacts[0].open("rb") as stream:
            header = transaction.hdrFromFdno(stream.fileno())
        identity = {key: header[key] for key in ("name", "version", "release", "arch")}
    finally:
        transaction.closeDB()
    if identity != {"name": "kyuubi_3_3_0", "version": "1.9.4", "release": "2.official.el8", "arch": "noarch"}:
        raise RuntimeError("RPM identity differs from the official binary packaging contract")
    result = {"schema_version": 1, "source": source["binary"], "identity": identity,
              "path": str(artifacts[0]), "sha256": digest(artifacts[0], "sha256")}
    (output / "receipt.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(package(arguments.archive, arguments.output), sort_keys=True))
