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
import unittest
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def parameters(types):
    return {"native_configs": {"schema_version": 1, "types": types}}



class NativeMetadataTests(unittest.TestCase):
    def test_metadata_declares_every_type_and_theme_property(self):
        for name in ("nginx", "postgresql", "kyuubi", "trino", "doris", "elasticsearch", "minio", "airflow", "celeborn", "dolphinscheduler"):
            base = ROOT / "mpacks" / name / "extensions" / name.upper() / "1.0/services" / name.upper()
            types = {p.stem: ElementTree.parse(p).getroot() for p in (base / "configuration").glob("*.xml")}
            metadata = ElementTree.parse(base / "metainfo.xml")
            self.assertEqual(metadata.findtext("services/service/themes/theme/fileName"), "theme.json")
            self.assertTrue(all(not list(e) for e in metadata.findall("services/service/requiredServices/service")))
            declared = {e.text for e in ElementTree.parse(base / "metainfo.xml").findall(".//configuration-dependencies/config-type")}
            self.assertTrue(set(types) <= declared)
            props = {kind + "/" + p.findtext("name") for kind, root in types.items() for p in root.findall("property")}
            theme = json.loads((base / "themes/theme.json").read_text())["configuration"]
            placed = [p["config"] for p in theme["placement"]["configs"]]
            self.assertEqual(set(placed), props)
            self.assertEqual(len(placed), len(set(placed)))


if __name__ == "__main__":
    unittest.main()
