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
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
from native_config import ConfigurationError
path = ROOT / "mpacks/postgresql/extensions/POSTGRESQL/1.0/services/POSTGRESQL/package/scripts/observer.py"
spec = importlib.util.spec_from_file_location("postgresql_content_test", str(path))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class PostgreSQLContentTests(unittest.TestCase):
    def test_native_parser_rejection_never_replaces_existing_database_configuration(self):
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "postgresql.conf").write_text("work_mem = '4MB'\n")
            request = {"parameters": {"port": "5432", "native_configs": {
                "schema_version": 1, "types": {"postgresql-conf": {"content": "invalid_option = 1\n"}}}}}
            def paths(value):
                return root if value == "/var/lib/pgsql/data" else Path(value)
            with patch.object(observer, "Path", side_effect=paths), patch("pwd.getpwnam", return_value=account), patch.object(
                    observer.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout=b"")):
                with self.assertRaises(ConfigurationError):
                    observer.configure_content(request, True, "postgresql.service")
            self.assertEqual((root / "postgresql.conf").read_text(), "work_mem = '4MB'\n")


if __name__ == "__main__":
    unittest.main()
