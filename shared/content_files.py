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

import fcntl
import hashlib
import os
import pwd
import tempfile
from contextlib import contextmanager
from pathlib import Path

from native_config import ConfigurationError, section


def render(parameters, kind, variables):
    values = section(parameters, kind)
    if not values:
        return None
    if set(values) != {"content"} or not values["content"].strip():
        raise ConfigurationError("A nonempty content property is required: " + kind)
    value = values["content"]
    for key, replacement in variables.items():
        value = value.replace("{{" + key + "}}", str(replacement))
    return value if value.endswith("\n") else value + "\n"


def safe_path(path):
    if any(item.is_symlink() for item in (path,) + tuple(path.parents)):
        raise ConfigurationError("Configuration paths must not traverse symbolic links")


def replace(path, data, uid, gid, mode):
    safe_path(path)
    fd, temporary = tempfile.mkstemp(prefix=".ambari-write-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), uid, gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def transaction(root, contents, validate, user):
    """Validate staged files, replace atomically, and restore on activation failure."""
    root = Path(root)
    safe_path(root)
    account = pwd.getpwnam(user)
    lock = root / ".ambari-content.lock"
    safe_path(lock)
    with lock.open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix=".ambari-config-", dir=str(root)) as temporary:
            stage = Path(temporary)
            os.chown(str(stage), account.pw_uid, account.pw_gid)
            # Native parsers resolve relative includes beside the candidate file.
            # Mirror untouched resources without copying or modifying their data.
            for existing in root.iterdir():
                if existing.name not in contents and not existing.name.startswith(".ambari"):
                    (stage / existing.name).symlink_to(existing)
            previous, staged = {}, {}
            for name, value in contents.items():
                if Path(name).name != name or name.startswith("."):
                    raise ConfigurationError("Invalid managed configuration filename")
                path = root / name
                safe_path(path)
                if path.exists():
                    status = path.stat()
                    previous[name] = (path.read_bytes(), status.st_uid, status.st_gid, status.st_mode & 0o777)
                else:
                    previous[name] = None
                staged[name] = stage / name
                replace(staged[name], value.encode("utf-8"), account.pw_uid, account.pw_gid, 0o600)
            validate(staged)
            changed = []
            try:
                for name, value in contents.items():
                    current = root / name
                    if (previous[name] is None and current.exists() or previous[name] is not None and
                            (not current.exists() or current.read_bytes() != previous[name][0])):
                        raise ConfigurationError("Configuration changed concurrently; retry after reconciliation")
                    # Retain the immediately preceding file for manual crash recovery.
                    if previous[name] is not None:
                        replace(root / (name + ".ambari-before"), previous[name][0], account.pw_uid, account.pw_gid, 0o600)
                    changed.append(name)
                    replace(root / name, value.encode("utf-8"), account.pw_uid, account.pw_gid, 0o600)
                yield {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in contents}
            except BaseException:
                for name in changed:
                    target = root / name
                    if target.exists() and target.read_bytes() not in (
                            contents[name].encode("utf-8"), previous[name][0] if previous[name] else b""):
                        raise ConfigurationError("Configuration changed during activation; retain the backup for reconciliation")
                for name in reversed(changed):
                    if previous[name] is None:
                        if (root / name).exists():
                            (root / name).unlink()
                    else:
                        replace(root / name, *previous[name])
                raise


def result(request, outcome, observations):
    return dict({key: request[key] for key in
                 ("schema_version", "definition_snapshot", "execution_id", "task_id", "action")},
                outcome=outcome, observations=observations)
