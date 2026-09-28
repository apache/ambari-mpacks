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
path = ROOT / "mpacks/nginx/extensions/NGINX/1.0/services/NGINX/package/scripts/observer.py"
spec = importlib.util.spec_from_file_location("nginx_content_test", str(path))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class NginxContentTests(unittest.TestCase):
    def test_native_parser_rejection_preserves_main_file_and_health_include(self):
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "conf.d").mkdir()
            (root / "nginx.conf").write_text("# original main\n")
            (root / "conf.d/ambari-managed.conf").write_text("# original health\n")
            request = {"parameters": {"listen_port": "8080", "native_configs": {
                "schema_version": 1, "types": {"nginx-conf": {"content": "invalid directive;\n"}}}}}
            with patch.object(observer, "ROOT", root), patch.object(observer, "platform_identity", return_value=("rocky", "8")), patch(
                    "pwd.getpwnam", return_value=account), patch.object(observer.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(ConfigurationError):
                    observer.configure(request)
            self.assertEqual((root / "nginx.conf").read_text(), "# original main\n")
            self.assertEqual((root / "conf.d/ambari-managed.conf").read_text(), "# original health\n")


if __name__ == "__main__":
    unittest.main()
