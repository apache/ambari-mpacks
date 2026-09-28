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

import ast
import hashlib
import json
import unittest
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
NEW = ("dolphinscheduler", "trino", "doris", "elasticsearch", "minio")


class NewReleaseTests(unittest.TestCase):
    def test_new_packs_have_exact_release_sources_components_and_password_metadata(self):
        release = json.loads((ROOT / "release.json").read_text())["packs"]
        for name in NEW:
            with self.subTest(name=name):
                home = ROOT / "mpacks" / name
                manifest = json.loads((home / "mpack.json").read_text())
                source = json.loads((home / "source.json").read_text())
                self.assertEqual(release[name], {"path": "mpacks/" + name, "version": manifest["version"]})
                self.assertEqual(manifest["name"], name)
                self.assertEqual(source["validation_status"], "IMPLEMENTED_PENDING_ACCEPTANCE")
                self.assertEqual(source["schema_version"], 1)
                binary = source.get("binary") or source.get("source")
                self.assertTrue(binary["url"].startswith("https://"))
                self.assertEqual(len(binary["sha512"]), 128)
                service = name.upper()
                base = home / "extensions" / service / "1.0/services" / service
                runtime = ast.parse((base / "package/scripts/runtime.py").read_text())
                constants = {target.id: ast.literal_eval(node.value) for node in runtime.body
                             if isinstance(node, ast.Assign) for target in node.targets
                             if isinstance(target, ast.Name) and target.id in
                             {"SHA512", "SOURCE_SHA512", "MINIO_SHA256", "CHECK_SHA256"}}
                self.assertEqual(constants.get("SHA512") or constants.get("SOURCE_SHA512"), binary["sha512"])
                if name == "minio":
                    self.assertEqual(constants["MINIO_SHA256"], source["build"]["minio_sha256"])
                    self.assertEqual(constants["CHECK_SHA256"], source["build"]["check_s3_sha256"])
                metadata = ElementTree.parse(base / "metainfo.xml").getroot()
                self.assertEqual(metadata.findtext("services/service/name"), service)
                components = {part.findtext("name") for part in metadata.findall("services/service/components/component")}
                self.assertTrue(components)
                config = ElementTree.parse(base / "configuration" / (name + "-env.xml")).getroot()
                properties = {item.findtext("name"): item for item in config.findall("property")}
                if name != "trino":
                    self.assertTrue(any(item.findtext("property-type") == "PASSWORD" for item in properties.values()))
                for item in properties.values():
                    if item.findtext("property-type") == "PASSWORD":
                        self.assertFalse(item.findtext("value"))
                links = json.loads((base / "quicklinks/quicklinks.json").read_text())["configuration"]["links"]
                for link in links:
                    self.assertIn(link["component_name"], components)
                    self.assertEqual(link["port"]["site"], name + "-env")
                    self.assertIn(link["port"]["http_property"], properties)

    def test_shared_file_locks_match_current_release(self):
        for name in NEW + ("nginx", "postgresql", "airflow", "celeborn", "kyuubi"):
            with self.subTest(name=name):
                manifest = json.loads((ROOT / "mpacks" / name / "shared-files.json").read_text())
                self.assertEqual(manifest["schema_version"], 1)
                for item in manifest["files"]:
                    self.assertEqual(hashlib.sha256((ROOT / item["source"]).read_bytes()).hexdigest(), item["digest"])
        for name in ("generic-base",):
            self.assertEqual(json.loads((ROOT / "release.json").read_text())["packs"][name]["version"],
                             {"nginx": "1.0.0.4", "postgresql": "1.0.0.5", "generic-base": "1.0.0.3"}[name])


if __name__ == "__main__":
    unittest.main()
