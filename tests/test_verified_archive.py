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

import hashlib
import io
import json
import sys
import tarfile
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
from managed_topology import assigned_hosts
import verified_archive
from verified_archive import extract, verify_install


def archive(path, entries):
    with tarfile.open(str(path), "w:gz") as stream:
        root = tarfile.TarInfo("software-1/")
        root.type = tarfile.DIRTYPE
        stream.addfile(root)
        for name, kind, content in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            if kind == tarfile.REGTYPE:
                entry.size = len(content)
                stream.addfile(entry, io.BytesIO(content))
            else:
                entry.linkname = content
                stream.addfile(entry)


class VerifiedArchiveTests(unittest.TestCase):
    def test_extracts_only_contained_members_and_verifies_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "software.tar.gz"
            archive(source, [("software-1/bin/tool", tarfile.REGTYPE, b"binary"),
                             ("software-1/link", tarfile.SYMTYPE, "bin/tool")])
            target = root / "installed"
            self.assertEqual(extract(source, target, "software-1"), 2)
            self.assertEqual((target / "link").read_bytes(), b"binary")
            sha = hashlib.sha256(b"binary").hexdigest()
            (target / ".ambari-receipt.json").write_text(json.dumps({
                "schema_version": 1, "name": "software", "version": "1",
                "archive_sha512": "a" * 128, "required_sha256": {"bin/tool": sha}}))
            self.assertEqual(verify_install(target, "software", "1", "a" * 128,
                                            ["bin/tool"])["verified_files"], 1)
            (target / "bin/tool").write_bytes(b"foreign")
            with self.assertRaises(ValueError):
                verify_install(target, "software", "1", "a" * 128, ["bin/tool"])

    def test_rejects_escape_duplicate_special_and_oversized_members(self):
        cases = [
            [("software-1/../escape", tarfile.REGTYPE, b"bad")],
            [("software-1/file", tarfile.REGTYPE, b"one"),
             ("software-1/file", tarfile.REGTYPE, b"two")],
            [("software-1/link", tarfile.SYMTYPE, "../../outside")],
            [("software-1/pipe", tarfile.FIFOTYPE, "")],
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for index, entries in enumerate(cases):
                source = root / (str(index) + ".tar.gz")
                archive(source, entries)
                with self.subTest(index=index), self.assertRaises(ValueError):
                    extract(source, root / ("target-" + str(index)), "software-1")
            source = root / "large.tar.gz"
            archive(source, [("software-1/file", tarfile.REGTYPE, b"large")])
            with self.assertRaises(ValueError):
                extract(source, root / "large", "software-1", maximum_expanded=4)
            self.assertFalse((root / "escape").exists())

    def test_topology_rejects_foreign_missing_and_duplicate_hosts(self):
        fields = {"coordinator_host": ("trino_coordinator_hosts", True, False),
                  "worker_hosts": ("trino_worker_hosts", False, True)}
        topology = {"trino_coordinator_hosts": ["coordinator.test"],
                    "trino_worker_hosts": ["worker.test"]}
        self.assertEqual(assigned_hosts({}, topology, fields),
                         {"coordinator_host": "coordinator.test", "worker_hosts": "worker.test"})
        for parameters, assigned in [
            ({"coordinator_host": "foreign.test"}, topology),
            ({}, {"trino_coordinator_hosts": []}),
            ({}, {"trino_coordinator_hosts": ["one.test", "two.test"]}),
            ({}, {"trino_coordinator_hosts": ["one.test"],
                  "trino_worker_hosts": ["worker.test", "worker.test"]}),
        ]:
            with self.subTest(parameters=parameters, assigned=assigned), self.assertRaises(ValueError):
                assigned_hosts(parameters, assigned, fields)

    def test_parallel_installers_publish_one_verified_distribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            calls = []
            def directory(path, *_):
                Path(path).mkdir(parents=True, exist_ok=True)
                return Path(path)
            def install(home, *_):
                calls.append(home)
                time.sleep(0.05)
                home.mkdir()
                return {"version": "1"}
            with patch.object(verified_archive, "require_platform"), patch.object(verified_archive, "ROOT", root), patch.object(
                    verified_archive, "directory", side_effect=directory), patch.object(
                    verified_archive, "_install_locked", side_effect=install), patch.object(
                    verified_archive, "verify_install", return_value={"version": "1"}):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(verified_archive.install_archive, "software", "1",
                        "https://example.test/software.tar.gz", "a" * 128, "software-1", ["bin/tool"])
                        for _ in range(2)]
                    self.assertEqual([future.result() for future in futures],
                                     [{"version": "1"}, {"version": "1"}])
            self.assertEqual(len(calls), 1)

    def test_non_arm_linux_host_is_rejected_before_install(self):
        with patch.object(verified_archive.platform, "system", return_value="Darwin"), self.assertRaises(ValueError):
            verified_archive.require_platform()
        with patch.object(verified_archive.platform, "system", return_value="Linux"), patch.object(
                verified_archive.platform, "machine", return_value="x86_64"), self.assertRaises(ValueError):
            verified_archive.require_platform()
