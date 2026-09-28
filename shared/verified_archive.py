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
import json
import os
import platform
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

from managed_runtime import directory, download, no_links
from observations import atomic_json

ROOT = Path("/opt/ambari-mpacks")
CACHE = Path("/var/cache/ambari-mpacks")


def require_platform():
    if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"}:
        raise ValueError("This distribution requires Linux ARM64")


def digest_file(path, algorithm):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(root, path):
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("Archive member leaves its distribution")


def extract(archive, target, prefix, maximum_expanded=16 * 1024 ** 3):
    target = Path(target)
    no_links(target)
    target.mkdir(mode=0o755)
    pending_links = []
    seen = set()
    expanded = 0
    with tarfile.open(str(archive), "r:gz") as source:
        for entry in source:
            parts = Path(entry.name).parts
            if not parts or parts[0] != prefix or ".." in parts or Path(entry.name).is_absolute():
                raise ValueError("Archive member leaves its pinned distribution")
            relative = Path(*parts[1:])
            if relative == Path("."):
                if not entry.isdir() or entry.size:
                    raise ValueError("Invalid distribution root")
                continue
            if len(seen) >= 250000 or str(relative) in seen:
                raise ValueError("Duplicate or excessive archive members")
            seen.add(str(relative))
            destination = target / relative
            no_links(destination)
            if entry.isdir() and entry.size == 0:
                destination.mkdir(parents=True, exist_ok=True)
                destination.chmod(0o755)
            elif entry.isfile() and not entry.issparse():
                expanded += entry.size
                if expanded > maximum_expanded:
                    raise ValueError("Expanded distribution exceeds its limit")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(entry) as incoming, destination.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                destination.chmod(0o755 if entry.mode & 0o111 else 0o644)
            elif (entry.issym() or entry.islnk()) and entry.size == 0:
                pending_links.append((destination, entry.linkname, entry.issym()))
            else:
                raise ValueError("Unsupported distribution member")
    for destination, link, symbolic in pending_links:
        link_path = Path(link)
        if link_path.is_absolute() or ".." in link_path.parts and not symbolic:
            raise ValueError("Invalid distribution link")
        candidate = destination.parent / link if symbolic else target / link_path.relative_to(prefix)
        resolved = candidate.resolve()
        _inside(target.resolve(), resolved)
        if not resolved.is_file() and not resolved.is_dir():
            raise ValueError("Distribution link target is missing")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if symbolic:
            destination.symlink_to(link)
        elif resolved.is_file():
            os.link(str(resolved), str(destination))
        else:
            raise ValueError("Hard link does not point to a file")
    return len(seen)


def verify_install(home, name, version, archive_sha512, required):
    home = Path(home)
    no_links(home)
    marker = home / ".ambari-receipt.json"
    no_links(marker)
    receipt = json.loads(marker.read_text())
    identity = {"schema_version": 1, "name": name, "version": version,
                "archive_sha512": archive_sha512}
    if any(type(receipt.get(key)) is not type(value) or receipt[key] != value
           for key, value in identity.items()):
        raise ValueError("Installed distribution identity differs")
    hashes = receipt.get("required_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(required):
        raise ValueError("Missing required distribution identity")
    for relative in required:
        path = home / relative
        no_links(path)
        if not path.is_file() or not isinstance(hashes[relative], str) or not re.fullmatch(r"[0-9a-f]{64}", hashes[relative]):
            raise ValueError("Required distribution file is missing")
        if digest_file(path, "sha256") != hashes[relative]:
            raise ValueError("Installed distribution file differs from its receipt")
    return {"name": name, "version": version, "archive_sha512": archive_sha512,
            "verified_files": len(required)}


def install_archive(name, version, url, archive_sha512, prefix, required,
                    maximum_archive=6 * 1024 ** 3, maximum_expanded=16 * 1024 ** 3):
    require_platform()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Invalid distribution identity")
    if not re.fullmatch(r"[0-9a-f]{128}", archive_sha512):
        raise ValueError("Invalid pinned archive digest")
    if not required or any(Path(path).is_absolute() or ".." in Path(path).parts
                           or Path(path) == Path(".") for path in required):
        raise ValueError("Invalid required file manifest")
    home = ROOT / name / version
    directory(home.parent, "root", 0o755)
    lock = home.parent / ".install.lock"
    no_links(lock)
    descriptor = os.open(str(lock), os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if home.exists():
            return verify_install(home, name, version, archive_sha512, required)
        return _install_locked(home, name, version, url, archive_sha512, prefix,
                               required, maximum_archive, maximum_expanded)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _install_locked(home, name, version, url, archive_sha512, prefix, required,
                    maximum_archive, maximum_expanded):
    cache = directory(CACHE, "root", 0o755) / (name + "-" + version + ".tar.gz")
    no_links(cache)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=str(home.parent)) as work:
        archive = cache
        if cache.exists():
            if digest_file(cache, "sha512") != archive_sha512:
                raise ValueError("Cached distribution differs from its pinned digest")
        else:
            archive = Path(work) / "distribution.tar.gz"
            download(url, archive, archive_sha512, maximum=maximum_archive)
        target = Path(work) / "distribution"
        extract(archive, target, prefix, maximum_expanded)
        hashes = {}
        for relative in required:
            path = target / relative
            no_links(path)
            if not path.is_file():
                raise ValueError("Pinned distribution lacks a required file")
            hashes[relative] = digest_file(path, "sha256")
        atomic_json(target / ".ambari-receipt.json", {"schema_version": 1, "name": name,
                    "version": version, "archive_sha512": archive_sha512,
                    "required_sha256": hashes})
        os.rename(str(target), str(home))
    return verify_install(home, name, version, archive_sha512, required)
