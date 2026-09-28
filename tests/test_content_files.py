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

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
from content_formats import parse_properties, parse_environment, parse_ini, render_ini
from content_files import transaction, render, result
from native_config import ConfigurationError, properties, render_properties, yaml_properties


def params(kind, text, **extra):
    return {"native_configs": {"schema_version": 1, "types": {kind: dict(extra, content=text)}}}


class ContentFileTests(unittest.TestCase):
    def test_content_preserves_trailing_escaped_spaces_and_blank_lines(self):
        source = "# comment\nvalue=trailing\\ \n\n"
        values = properties(params("site", source), "site")
        self.assertEqual(values["value"], "trailing ")
        self.assertEqual(render_properties(values), source)
        self.assertEqual(render(params("nginx-conf", "# comment \n\n"), "nginx-conf", {}), "# comment \n\n")

    def test_properties_support_comments_continuations_escapes_and_last_value(self):
        source = "# keep comment\nx=first\nx : last\\ value\nurl=jdbc:postgresql://host/db\nlong=one\\\n  two\nunicode=\\u4e2d\n"
        value = parse_properties(source)
        self.assertEqual(value["x"], "last value")
        self.assertEqual(value["long"], "onetwo")
        self.assertEqual(value["unicode"], "\u4e2d")
        self.assertEqual(value["url"], "jdbc:postgresql://host/db")
        rendered = render_properties(properties(params("trino-config", source, x="obsolete"), "trino-config", {"coordinator": "true"}))
        self.assertTrue(rendered.startswith(source))
        self.assertIn("coordinator=true\n", rendered)
        self.assertNotIn("obsolete", rendered)

    def test_managed_conflicts_are_explicit_and_matching_values_are_allowed(self):
        source = "# exact user document\nhttp.port=9200\n"
        value = properties(params("test", source), "test", {"http.port": 9200}, reserved=("http.",))
        self.assertEqual(render_properties(value), source)
        with self.assertRaises(ConfigurationError):
            properties(params("test", "http.port=9201"), "test", {"http.port": 9200})

    def test_ini_preserves_comments_and_adds_missing_managed_values(self):
        source = "# heading\n[core]\n# user comment\nload_examples = False\n\n[logging]\nlogging_level = INFO\n"
        doc = parse_ini(source)
        values = dict(doc, **{"core.executor": "LocalExecutor", "database.sql_alchemy_conn": "postgresql://local"})
        output = render_ini(doc, values)
        self.assertIn("# user comment\nload_examples = False", output)
        self.assertEqual(parse_ini(output), values)

    def test_environment_values_are_literal_and_command_lines_are_rejected(self):
        values = parse_environment("# note\nJAVA_OPTS='-Xmx1g -Dname=$NAME'\nEMPTY=\n")
        self.assertEqual(values["JAVA_OPTS"], "-Xmx1g -Dname=$NAME")
        self.assertEqual(values["EMPTY"], "")
        with self.assertRaises(ValueError):
            parse_environment("run-some-command\n")

    def test_invalid_yaml_and_duplicate_keys_are_rejected(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is required for YAML content verification")
        source = "# keep YAML\nsearch:\n  max_buckets: 1000\nnode.attr.rack: 'rack: 1'\n"
        doc = properties(params("elasticsearch-settings", source), "elasticsearch-settings", {"http.port": 9200})
        self.assertTrue(yaml_properties(doc).startswith(source))
        self.assertEqual(yaml.safe_load(yaml_properties(doc))["http.port"], 9200)
        for bad in ("x: 1\nx: 2\n", "not a mapping", "x: ["):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                properties(params("elasticsearch-settings", bad), "elasticsearch-settings")

    def test_native_validation_precedes_replacement_and_activation_failure_restores_files(self):
        account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with tempfile.TemporaryDirectory() as directory, patch("pwd.getpwnam", return_value=account):
            root = Path(directory).resolve()
            (root / "config.conf").write_text("original\n")
            (root / "config.conf").chmod(0o640)
            (root / "extra.conf").write_text("included=value\n")
            def reject(staged):
                self.assertEqual(staged["config.conf"].read_text(), "invalid\n")
                self.assertEqual((staged["config.conf"].parent / "extra.conf").read_text(), "included=value\n")
                self.assertEqual((root / "config.conf").read_text(), "original\n")
                raise ConfigurationError("native parser rejected")
            with self.assertRaises(ConfigurationError):
                with transaction(root, {"config.conf": "invalid\n"}, reject, "root"):
                    self.fail("Invalid content was accepted")
            self.assertEqual((root / "config.conf").read_text(), "original\n")
            with self.assertRaises(RuntimeError):
                with transaction(root, {"config.conf": "new\n", "new.conf": "new\n"}, lambda s: None, "root"):
                    self.assertEqual((root / "config.conf").read_text(), "new\n")
                    raise RuntimeError("activation failed")
            self.assertEqual((root / "config.conf").read_text(), "original\n")
            self.assertEqual((root / "config.conf").stat().st_mode & 0o777, 0o640)
            self.assertFalse((root / "new.conf").exists())
            with transaction(root, {"config.conf": "recovered\n"}, lambda s: None, "root") as receipt:
                self.assertEqual(len(receipt["config.conf"]), 64)
            self.assertEqual((root / "config.conf").read_text(), "recovered\n")

    def test_managed_placeholder_expansion_does_not_change_application_variables(self):
        values = params("nginx-conf", "listen {{listen_port}};\nreturn 200 '$host ${uri}';\n")
        self.assertEqual(render(values, "nginx-conf", {"listen_port": 8080}),
                         "listen 8080;\nreturn 200 '$host ${uri}';\n")
        with self.assertRaises(ConfigurationError):
            render(params("nginx-conf", ""), "nginx-conf", {})

    def test_results_never_echo_configuration_content(self):
        request = dict(schema_version=1, definition_snapshot="a"*64,
                       execution_id="12345678-1234-4234-8234-123456789abc",
                       task_id=1, action="configure", parameters={"content": "private value"})
        observed = result(request, "APPLIED", {"files": {}})
        self.assertNotIn("parameters", observed)
        self.assertNotIn("private value", json.dumps(observed))


if __name__ == "__main__":
    unittest.main()
