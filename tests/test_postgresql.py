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

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
path = ROOT / "mpacks/postgresql/extensions/POSTGRESQL/1.0/services/POSTGRESQL/package/scripts/observer.py"
spec = importlib.util.spec_from_file_location("postgresql_observer", str(path))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
BACKUP = "12345678-1234-4234-8234-123456789abc"


def descriptor():
    return {"schema_version": 1, "backup_id": BACKUP, "execution_id": BACKUP,
            "definition_snapshot": "a" * 64, "task_id": 57, "payload_digest": "b" * 64,
            "source": {"database": "source", "instance_id": "7689102948144019413",
                       "server_version_num": 100023,
                       "tables": {"public.rows": {"rows": 10, "digest": "c" * 64}}}}


class BackupDescriptorTests(unittest.TestCase):
    def test_accepts_exact_backup_lineage_and_empty_database(self):
        value = descriptor()
        self.assertEqual(observer.validate_backup(value, BACKUP, "source"), value)
        value["source"]["tables"] = {}
        self.assertEqual(observer.validate_backup(value, BACKUP, "source"), value)

    def test_rejects_missing_foreign_or_invalid_descriptor_before_restoration(self):
        changes = [lambda r: r.update(schema_version=True), lambda r: r.pop("definition_snapshot"),
                   lambda r: r.update(execution_id="22345678-1234-4234-8234-123456789abc"),
                   lambda r: r.update(task_id=True), lambda r: r.update(task_id=None),
                   lambda r: r.update(payload_digest="invalid"),
                   lambda r: r["source"].update(instance_id=123),
                   lambda r: r["source"].update(database="foreign"),
                   lambda r: r["source"].update(server_version_num="100023"),
                   lambda r: r["source"].pop("tables"),
                   lambda r: r["source"]["tables"]["public.rows"].update(rows=True),
                   lambda r: r["source"]["tables"]["public.rows"].update(digest="invalid")]
        for index, change in enumerate(changes):
            value = copy.deepcopy(descriptor())
            change(value)
            with self.subTest(case=index), self.assertRaises(ValueError):
                observer.validate_backup(value, BACKUP, "source")


if __name__ == "__main__":
    unittest.main()
