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

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("binary_packaging", str(ROOT / "tools/package_kyuubi_binary.py"))
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class BinaryPackagingTests(unittest.TestCase):
    def test_unverified_binary_never_creates_a_workspace_or_runs_rpm(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "input.tgz"
            archive.write_bytes(b"another release, despite a successful download")
            output = Path(directory) / "output"
            with patch.object(packaging.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    packaging.package(archive, output)
                run.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
