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

"""Restore verified Spark payloads for Bigtop packaging without compiling Spark."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
import rpm


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def restore(inputs):
    state = json.loads((inputs / "state.json").read_text())
    require(type(state.get("schema_version")) is int and state["schema_version"] == 2, "Unsupported build-state schema")
    require(state.get("run_id") == "bigtop360-rocky9-arm64-v4", "Foreign source run")
    require(state["context"]["platform"] == {"name": "rocky", "version": "9", "architecture": "aarch64"}, "Unexpected source platform")
    component = state["components"]["spark"]
    require(component["status"] == "completed" and len(component["artifacts"]) == 11, "Incomplete Spark artifact set")
    target = Path.cwd() / "dist"
    require(not target.exists(), "Refusing to replace an existing distribution")
    transaction = rpm.TransactionSet()
    with tempfile.TemporaryDirectory(prefix="verified-spark-") as directory:
        root = Path(directory)
        for artifact in component["artifacts"]:
            relative = Path(artifact["path"])
            require(not relative.is_absolute() and ".." not in relative.parts, "Invalid artifact path")
            package = inputs / "artifacts" / relative
            require(package.is_file() and not package.is_symlink() and type(artifact["size"]) is int
                    and package.stat().st_size == artifact["size"] and digest(package) == artifact["sha256"],
                    "Input RPM differs from the completed component receipt")
            with package.open("rb") as stream:
                header = transaction.hdrFromFdno(stream.fileno())
            require(header["version"] == "3.5.8" and header["arch"] == "noarch" and header["filedigestalgo"] == 8,
                    "Unexpected RPM identity or digest algorithm")
            require(all(".." not in Path(name).parts for name in header["filenames"]), "Unsafe RPM member")
            producer = subprocess.Popen(["rpm2cpio", str(package)], stdout=subprocess.PIPE)
            try:
                extracted = subprocess.run(["cpio", "-idm", "--quiet", "--no-absolute-filenames"],
                    cwd=str(root), stdin=producer.stdout, check=False)
                producer.stdout.close()
                require(producer.wait() == 0 and extracted.returncode == 0, "RPM extraction failed")
            finally:
                if producer.poll() is None:
                    producer.kill()
                    producer.wait()
            for name, mode, expected in zip(header["filenames"], header["filemodes"], header["filedigests"]):
                if stat.S_ISREG(mode):
                    require(expected and digest(root / name.lstrip("/")) == expected, "Extracted payload differs from its RPM header")
        original = root / "usr/bigtop/3.6.0/usr/lib/spark"
        require((original / "jars").is_dir(), "Missing Spark runtime")
        shutil.copytree(str(original), str(target), symlinks=True)
        for name in ("conf", "work", "logs"):
            path = target / name
            if path.is_symlink():
                path.unlink()
        shutil.copytree(str(root / "usr/bigtop/3.6.0/etc/spark/conf.dist"), str(target / "conf"))
        for directory in ("examples/jars", "yarn/lib", "external/lib"):
            path = target / directory
            if path.is_dir():
                for link in path.iterdir():
                    if link.is_symlink():
                        link.unlink()
        for launcher in Path("bin").glob("*.cmd"):
            shutil.copy2(str(launcher), str(target / "bin" / launcher.name))
        sources = Path(os.environ["RPM_SOURCE_DIR"])
        shutil.copy2(str(original / "LICENSE"), str(sources / "LICENSE-binary"))
        licenses = sources / "licenses-binary"
        if licenses.exists():
            shutil.rmtree(str(licenses))
        shutil.copytree(str(original / "licenses"), str(licenses))
        jars = {str(path.relative_to(target)): digest(path) for path in target.rglob("*.jar")
                if path.is_file() and not path.is_symlink()}
        require(jars, "No verified runtime JARs")
        (Path.cwd() / "reused-spark-payload.json").write_text(json.dumps({
            "schema_version": 1, "source_run": state["run_id"], "source_context": state["context_fingerprint"],
            "source_version": "3.5.8", "compiled": False, "jars": jars}, sort_keys=True))
    transaction.closeDB()
    print(json.dumps({"schema_version": 1, "restored_jars": len(jars), "compiled": False}))


if __name__ == "__main__":
    restore(Path(sys.argv[1]))
