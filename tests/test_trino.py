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
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
PATH = ROOT / "mpacks/trino/extensions/TRINO/1.0/services/TRINO/package/scripts/runtime.py"
spec = importlib.util.spec_from_file_location("trino_runtime_test", str(PATH))
trino = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trino)


class Response:
    status = 200

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, maximum):
        return json.dumps(self.value).encode()


class Opener:
    def __init__(self, values):
        self.values = iter(values)

    def open(self, request, timeout):
        return Response(next(self.values))


class TrinoTests(unittest.TestCase):
    def test_readiness_waits_for_startup_but_rejects_foreign_versions(self):
        ready = {"nodeId": "node-1", "state": "ACTIVE", "starting": False,
                 "coordinator": True, "environment": "production", "nodeVersion": {"version": "483"}}
        with patch.object(trino, "json_http", side_effect=[dict(ready, starting=True), ready]), patch.object(trino.time, "sleep"):
            self.assertEqual(trino.ready_info("http://trino.test/v1/info", "production", True)["nodeId"], "node-1")
        with patch.object(trino, "json_http", return_value=dict(ready, nodeVersion={"version": "other"})), patch.object(
                trino.time, "sleep") as sleep, self.assertRaises(ValueError):
            trino.ready_info("http://trino.test/v1/info", "production", True)
        sleep.assert_not_called()

    def test_node_info_requires_exact_version_role_and_active_state(self):
        value = {"nodeId": "node-1", "state": "ACTIVE", "starting": False,
                 "coordinator": True, "environment": "production", "nodeVersion": {"version": "483"}}
        self.assertEqual(trino.validate_info(value, "483", "production", True)["nodeId"], "node-1")
        for key, bad in (("nodeId", ""), ("state", "INACTIVE"), ("starting", True),
                         ("coordinator", False), ("environment", "other"),
                         ("nodeVersion", {"version": "482"})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                trino.validate_info(dict(value, **{key: bad}), "483", "production", True)

    def test_statement_follows_only_exact_query_lineage_and_origin(self):
        first = {"id": "query-1", "nextUri": "http://trino.test:8086/v1/statement/query-1/1",
                 "stats": {"state": "RUNNING"}}
        final = {"id": "query-1", "data": [[25]], "stats": {"state": "FINISHED"}}
        with patch.object(trino.urllib.request, "build_opener", return_value=Opener([first, final])):
            self.assertEqual(trino.statement("http://trino.test:8086", "SELECT 1"), ("query-1", [[25]]))
        for terminal in (dict(final, id="query-2"), dict(final, stats={"state": "FAILED"}),
                         dict(final, error={"message": "failed"})):
            with self.subTest(terminal=terminal), patch.object(
                    trino.urllib.request, "build_opener", return_value=Opener([first, terminal])), self.assertRaises(ValueError):
                trino.statement("http://trino.test:8086", "SELECT 1")
        foreign = dict(first, nextUri="http://foreign.test:8086/v1/statement/query-1/1")
        with patch.object(trino.urllib.request, "build_opener", return_value=Opener([foreign])), self.assertRaises(ValueError):
            trino.statement("http://trino.test:8086", "SELECT 1")

    def test_check_rejects_incorrect_query_result_and_duplicate_nodes(self):
        settings = ("check", "coordinator.test", ["worker.test"], "worker.test", 8086,
                    Path("/usr/lib/jvm/temurin-25"), "2G", "production")
        coordinator = {"nodeId": "coordinator-id", "state": "ACTIVE", "starting": False,
                       "coordinator": True, "environment": "production", "nodeVersion": {"version": "483"}}
        worker = dict(coordinator, nodeId="worker-id", coordinator=False)
        with patch.object(trino, "settings", return_value=settings), patch.object(
                trino, "json_http", side_effect=[coordinator, worker]), patch.object(
                trino, "statement", return_value=("query-1", [[25]])):
            self.assertEqual(trino.check({})["query_id"], "query-1")
        for rows in ([[True]], [[24]], [], [[25], [25]]):
            with self.subTest(rows=rows), patch.object(trino, "settings", return_value=settings), patch.object(
                    trino, "json_http", side_effect=[coordinator, worker]), patch.object(
                    trino, "statement", return_value=("query-1", rows)), self.assertRaises(ValueError):
                trino.check({})
        with patch.object(trino, "settings", return_value=settings), patch.object(
                trino, "json_http", side_effect=[coordinator, dict(worker, nodeId="coordinator-id")]), self.assertRaises(ValueError):
            trino.check({})


if __name__ == "__main__":
    unittest.main()
