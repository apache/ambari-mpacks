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

import configparser
import re
import shlex


class Document(dict):
    def __init__(self, values, source, format_name):
        super().__init__(values)
        self.source = source
        self.format_name = format_name
        self.explicit = set(values)


def unescape(value):
    result, index = [], 0
    while index < len(value):
        char = value[index]
        index += 1
        if char == "\\" and index < len(value):
            char = value[index]
            index += 1
            if char == "u":
                digits = value[index:index + 4]
                if not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    raise ValueError("Invalid Unicode escape in properties content")
                char = chr(int(digits, 16))
                index += 4
            else:
                char = {"n": "\n", "r": "\r", "t": "\t", "f": "\f"}.get(char, char)
        result.append(char)
    return "".join(result).encode("utf-16", "surrogatepass").decode("utf-16")


def parse_properties(source):
    values, pending = {}, ""
    for physical in source.splitlines():
        line = pending + physical.lstrip(" \t\f")
        if not pending and (not line or line.startswith(("#", "!"))):
            continue
        if (len(line) - len(line.rstrip("\\"))) % 2:
            pending = line[:-1]
            continue
        pending = ""
        escaped, boundary = False, len(line)
        for index, char in enumerate(line):
            if not escaped and char in "=: \t\f":
                boundary = index
                break
            escaped = not escaped if char == "\\" else False
        tail = line[boundary:].lstrip(" \t\f")
        if tail.startswith(("=", ":")):
            tail = tail[1:].lstrip(" \t\f")
        values[unescape(line[:boundary])] = unescape(tail)
    if pending:
        raise ValueError("Incomplete continuation in properties content")
    return Document(values, source, "properties")


def parse_environment(source):
    values = {}
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=(.*)", line)
        if not match:
            raise ValueError("Environment content requires NAME=value assignments")
        key, value = match.groups()
        parts = shlex.split(value, comments=True)
        if len(parts) > 1:
            raise ValueError("Quote environment values containing spaces")
        values[key] = parts[0] if parts else ""
    return Document(values, source, "environment")


def without_properties(source, keys):
    result, pending = [], ""
    for line in source.splitlines(keepends=True):
        pending += line
        physical = line.rstrip("\r\n")
        if (len(physical) - len(physical.rstrip("\\"))) % 2:
            continue
        if not set(parse_properties(pending)) & set(keys):
            result.append(pending)
        pending = ""
    if pending:
        raise ValueError("Incomplete continuation in properties content")
    return "".join(result)


def parse_yaml(source):
    import yaml
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError("Duplicate YAML configuration key")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    data = yaml.load(source, Loader=UniqueLoader)
    if not isinstance(data, dict):
        raise ValueError("YAML configuration must be a mapping")
    import json
    flattened = {}
    def flatten(node, prefix=""):
        for key, value in node.items():
            if not isinstance(key, str):
                raise ValueError("YAML setting names must be strings")
            name = prefix + key
            if isinstance(value, dict):
                flatten(value, name + ".")
            else:
                if name in flattened:
                    raise ValueError("Ambiguous nested and dotted YAML setting")
                flattened[name] = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
    flatten(data)
    return Document(flattened, source, "yaml")


def parse_ini(source):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(source)
    if parser.defaults():
        raise ValueError("Use explicit INI sections instead of DEFAULT")
    return Document({group + "." + key: value for group in parser.sections()
                     for key, value in parser.items(group)}, source, "ini")


def preserve(document, rendered_missing):
    source = document.source if document.source.endswith("\n") else document.source + "\n"
    return source + (
        "\n# Ambari managed settings and defaults\n" + rendered_missing if rendered_missing else "")


def render_ini(document, values):
    missing = {key: value for key, value in values.items() if key not in document.explicit}
    result, current = [], None
    def finish(group):
        for key in list(missing):
            section, option = key.split(".", 1)
            if section == group:
                result.append(option + " = " + str(missing.pop(key)))
    for line in document.source.splitlines():
        match = configparser.ConfigParser.SECTCRE.match(line.strip())
        if match:
            finish(current)
            current = match.group("header")
        result.append(line)
    finish(current)
    for group in sorted({key.split(".", 1)[0] for key in missing}):
        result.extend(["", "[" + group + "]"])
        finish(group)
    return "\n".join(result) + "\n"
