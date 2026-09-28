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
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
import native_config as native


def parameters(types):
    return {"native_configs": {"schema_version": 1, "types": types}}



class NativeConfigurationTests(unittest.TestCase):
    def test_collect_scopes_types_to_service_and_preserves_custom_values(self):
        values = native.collect({"trino-env": {"heap_size": "2G"}, "trino-config": {
            "query.max-history": "30"}, "hive-site": {"secret": "unrelated"}}, "trino")
        self.assertEqual(values, {"schema_version": 1, "types": {"trino-config": {"query.max-history": "30"}}})
        with self.assertRaises(native.ConfigurationError):
            native.section({"native_configs": {"schema_version": True, "types": {}}}, "trino-config")

    def test_custom_properties_roundtrip_escaping_and_managed_conflicts(self):
        request = parameters({"trino-config": {"query.max-history": "50", "sample.path": r"C:\data x"}})
        result = native.properties(request, "trino-config", {"coordinator": "true"}, {"query.max-history": "100"})
        self.assertEqual(result["query.max-history"], "50")
        self.assertIn(r"sample.path=C:\\data\ x", native.render_properties(result))
        request["native_configs"]["types"]["trino-config"]["coordinator"] = "false"
        with self.assertRaisesRegex(native.ConfigurationError, "trino-config/coordinator"):
            native.properties(request, "trino-config", {"coordinator": "true"})
        for value in ("secret\ncoordinator=false", "secret\x00"):
            with self.assertRaises(native.ConfigurationError) as error:
                native.properties(parameters({"test": {"token": value}}), "test")
            self.assertNotIn("secret", str(error.exception))

    def test_properties_overlay_replaces_continuations_and_preserves_unrelated_values(self):
        original = "# comment\nworker.name=old\\\n  continuation\nother=value\n"
        rendered = native.overlay_properties(original, {"worker.name": "new"})
        self.assertEqual(rendered, "# comment\nother=value\nworker.name=new\n")

    def test_java_properties_escape_unicode_for_stream_and_reader_loaders(self):
        self.assertEqual(native.render_properties({"label": "\u4e2d\U0001f600"}),
                         "label=\\u4e2d\\ud83d\\ude00\n")

    def test_content_and_jvm_validation_rejects_bad_input_without_echoing_it(self):
        self.assertEqual(native.jvm_options(parameters({"jvm": {"content": "# comment\n-XX:+UseG1GC\n"}}), "jvm", ""), ["-XX:+UseG1GC"])
        for value in ("-Xmx4g", "-Xms4g", "-XX:MaxRAMPercentage=80", "-Dsecret=hello world", "not-an-option"):
            with self.assertRaises(native.ConfigurationError):
                native.jvm_options(parameters({"jvm": {"content": value}}), "jvm", "")
        for value in ("<broken>", '<!DOCTYPE x [<!ENTITY x "secret">]><x/>'):
            with self.assertRaises(native.ConfigurationError):
                native.content(parameters({"log": {"content": value}}), "log", xml=True)
        with self.assertRaises(native.ConfigurationError):
            native.content(parameters({"log": {"ignored": "x"}}), "log")

    def test_catalog_validation_rejects_duplicates_traversal_and_missing_check_catalog(self):
        valid = {"tpch": {"connector.name": "tpch"}, "memory": {"connector.name": "memory"}}
        self.assertEqual(set(native.catalogs(parameters({"trino-catalogs": {"content": json.dumps(valid)}}))), {"tpch.properties", "memory.properties"})
        bad = ['{"tpch":{"connector.name":"tpch"},"tpch":{}}',
               '{"tpch":{"connector.name":"tpch","connector.name":"other"}}',
               '{"../tpch":{"connector.name":"tpch"}}', '{}', '{"tpch":{"connector.name":12}}']
        for value in bad:
            with self.subTest(value=value), self.assertRaises(native.ConfigurationError):
                native.catalogs(parameters({"trino-catalogs": {"content": value}}))

    def test_yaml_values_preserve_strings_and_support_native_types(self):
        result = native.yaml_properties({"node.attr.rack": "rack: 1", "search.max_buckets": "1000",
                                        "action.destructive_requires_name": "true", "node.roles": '["data","master"]'})
        self.assertIn('"node.attr.rack": "rack: 1"', result)
        self.assertIn('"search.max_buckets": 1000', result)
        self.assertIn('"node.roles": ["data", "master"]', result)

    def test_shell_environment_is_literal_and_cannot_override_managed_paths(self):
        value = "$(touch /tmp/not-executed)"
        rendered = native.shell_exports(native.environment(parameters({"env": {"EXTRA": value}}), "env"))
        self.assertEqual(rendered, "export EXTRA='$(touch /tmp/not-executed)'\n")
        with self.assertRaises(native.ConfigurationError):
            native.environment(parameters({"env": {"JAVA_HOME": "/foreign"}}), "env", {"JAVA_HOME": "/managed"})



if __name__ == "__main__":
    unittest.main()
