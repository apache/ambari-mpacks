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
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
import observations


def request():
    return {"schema_version": 1, "definition_snapshot": "a" * 64,
            "execution_id": "12345678-1234-4234-8234-123456789abc",
            "task_id": 57, "action": "version", "parameters": {}}


class ObservationTests(unittest.TestCase):
    def systemd(self, unit="nginx.service", state="inactive", load="loaded", job_unit="nginx.service",
                job_path="/job/7", job_result="done"):
        manager, properties, bus = MagicMock(), MagicMock(), MagicMock()
        callbacks = []
        bus.add_signal_receiver.side_effect = lambda callback, **kw: callbacks.append(callback) or MagicMock()
        bus.get_object.side_effect = lambda destination, path: properties if path == "/unit/nginx" else manager
        manager.GetUnit.side_effect = RuntimeError("Stopped unit was garbage-collected")
        manager.LoadUnit.return_value = "/unit/nginx"
        properties.GetAll.return_value = {"Id": unit, "ActiveState": state, "LoadState": load}

        def stop(name, mode):
            callbacks[0](99, "/job/99", "other.service", "done")
            callbacks[0](7, job_path, job_unit, job_result)
            return "/job/7"

        manager.StopUnit.side_effect = stop
        dbus = SimpleNamespace(SystemBus=lambda: bus, Interface=lambda obj, interface: obj)
        glib = SimpleNamespace(MainContext=SimpleNamespace(default=MagicMock()))
        with patch.dict(sys.modules, {"dbus": dbus, "dbus.mainloop": SimpleNamespace(),
                "dbus.mainloop.glib": SimpleNamespace(DBusGMainLoop=lambda **kw: None),
                "gi": SimpleNamespace(), "gi.repository": SimpleNamespace(GLib=glib)}), patch.object(
                observations.time, "monotonic", side_effect=[0, 61]):
            try:
                return observations.unit_observation("nginx.service", "stop")
            finally:
                manager.GetUnit.assert_not_called()
                manager.Unsubscribe.assert_called_once()
                bus.close.assert_called_once()

    def test_stopped_unit_is_loaded_for_authoritative_inactive_observation(self):
        value = self.systemd()
        self.assertEqual(value, {"unit": "nginx.service", "active_state": "inactive",
                                "job": {"job_id": 7, "job_path": "/job/7",
                                        "unit": "nginx.service", "result": "done"}})

    def test_stop_rejects_missing_foreign_failed_or_unmatched_observations(self):
        for change in ({"unit": "other.service"}, {"state": "active"}, {"load": "not-found"},
                       {"job_unit": "other.service"}, {"job_result": "failed"}, {"job_path": "/job/6"}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.systemd(**change)

    def test_rpm_identity_comes_from_unique_database_record(self):
        header = {"name": "nginx", "version": "1.14.1", "release": "9.el8",
                  "epoch": 1, "arch": "aarch64"}
        transaction = MagicMock()
        transaction.dbMatch.return_value = [header]
        with patch.object(observations, "platform_identity", return_value=("rocky", "8")), patch.dict(
                sys.modules, {"rpm": SimpleNamespace(TransactionSet=lambda: transaction)}):
            value = observations.package_observation("nginx")
        self.assertEqual(value, {"package": "nginx", "version": "1.14.1",
                               "release": "9.el8", "epoch": 1, "architecture": "aarch64", "manager": "rpm"})
        transaction.dbMatch.assert_called_once_with("name", "nginx")
        transaction.closeDB.assert_called_once()

    def test_absent_ambiguous_or_foreign_rpm_is_unresolved(self):
        for rows in ([], [{"name": "other"}], [{"name": "nginx"}, {"name": "nginx"}]):
            with self.subTest(rows=rows):
                transaction = MagicMock()
                transaction.dbMatch.return_value = rows
                with patch.object(observations, "platform_identity", return_value=("rocky", "8")), patch.dict(
                        sys.modules, {"rpm": SimpleNamespace(TransactionSet=lambda: transaction)}):
                    with self.assertRaises(RuntimeError):
                        observations.package_observation("nginx")
                transaction.closeDB.assert_called_once()

    def test_schema_and_task_identity_require_exact_types(self):
        for key, value in (("schema_version", True), ("task_id", True), ("task_id", "57"), ("task_id", -1)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                observations.validate_request(dict(request(), **{key: value}))
        self.assertEqual(observations.validate_request(request()), request())
        background = dict(request(), task_id=None)
        self.assertEqual(observations.validate_request(background), background)

    def test_result_rejects_missing_foreign_and_empty_observations(self):
        source = request()
        valid = dict(source, outcome="APPLIED", observations={"software": {"package": "nginx"}})
        self.assertEqual(observations.validate_result(source, valid), valid)
        changes = (("schema_version", True), ("task_id", 58), ("task_id", "57"),
                   ("execution_id", "22345678-1234-4234-8234-123456789abc"),
                   ("definition_snapshot", "b" * 64), ("action", "start"),
                   ("outcome", "UNRESOLVED"), ("observations", {}), ("observations", []))
        for key, value in changes:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                observations.validate_result(source, dict(valid, **{key: value}))
        for key in ("schema_version", "task_id", "definition_snapshot", "execution_id", "action"):
            broken = copy.deepcopy(valid)
            del broken[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                observations.validate_result(source, broken)

    def test_rocky_platform_fields_are_machine_readable_and_exact(self):
        with patch.object(Path, "read_text", return_value='ID="rocky"\nVERSION_ID="8.10"\n'):
            self.assertEqual(observations.platform_identity(), ("rocky", "8"))
        for text in ('ID="rocky"\nVERSION_ID="9.4"\n', 'NAME="rocky 8"\n',
                     'ID="rocky"\nID="rocky"\nVERSION_ID="8.10"\n'):
            with patch.object(Path, "read_text", return_value=text), self.assertRaises(ValueError):
                observations.platform_identity()


if __name__ == "__main__":
    unittest.main()
