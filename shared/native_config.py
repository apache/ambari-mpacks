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
import re
import shlex
from xml.etree import ElementTree

MAX_CONTENT = 256 * 1024
LOG4J_DEFAULT = """rootLogger.level = info
rootLogger.appenderRef.console.ref = console
appender.console.type = Console
appender.console.name = console
appender.console.layout.type = PatternLayout
appender.console.layout.pattern = %d{ISO8601} %-5p %c - %m%n
"""


class ConfigurationError(ValueError):
    """Messages contain metadata identifiers, never configuration values."""


def collect(configurations, service):
    types = {name: dict(values) for name, values in configurations.items()
             if name.startswith(service + "-") and name != service + "-env"}
    for name, values in types.items():
        validate_properties(values, name, multiline=True)
    return {"schema_version": 1, "types": types}


def section(parameters, name):
    envelope = parameters.get("native_configs", {"schema_version": 1, "types": {}})
    if (not isinstance(envelope, dict) or type(envelope.get("schema_version")) is not int
            or envelope["schema_version"] != 1 or not isinstance(envelope.get("types"), dict)):
        raise ConfigurationError("Invalid native configuration schema")
    values = envelope["types"].get(name, {})
    validate_properties(values, name, multiline=True)
    return dict(values)


def validate_properties(values, name, multiline=False):
    if not isinstance(values, dict) or len(values) > 4096:
        raise ConfigurationError("Invalid configuration property map: " + name)
    for key, value in values.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\[\]-]*", key):
            raise ConfigurationError("Invalid property name in " + name)
        if (not isinstance(value, str) or len(value.encode("utf-8")) > MAX_CONTENT
                or "\x00" in value or not multiline and any(c in value for c in "\r\n")):
            raise ConfigurationError("Invalid property value in " + name + ": " + key)


def properties(parameters, name, managed=None, defaults=None, reserved=()):
    values = section(parameters, name)
    validate_properties(values, name)
    managed = {key: str(value) for key, value in (managed or {}).items()}
    for key, value in values.items():
        if key.startswith(tuple(reserved)) or key in managed and value != managed[key]:
            raise ConfigurationError("Property is managed by the basic settings: " + name + "/" + key)
    result = {key: str(value) for key, value in (defaults or {}).items()}
    result.update(values)
    result.update(managed)
    return result


def render_properties(values):
    validate_properties(values, "properties")
    def escape(value):
        value = value.replace("\\", "\\\\").replace("\t", "\\t").replace(" ", "\\ ")
        units = value.encode("utf-16-be")
        return "".join(chr(int.from_bytes(units[i:i + 2], "big"))
                       if 32 <= int.from_bytes(units[i:i + 2], "big") <= 126
                       else "\\u%04x" % int.from_bytes(units[i:i + 2], "big")
                       for i in range(0, len(units), 2))
    return "".join(key + "=" + escape(value) + "\n" for key, value in sorted(values.items()))


def overlay_properties(original, values):
    lines, skipping = [], False
    for line in original.splitlines():
        if not skipping:
            key = re.split(r"[\s=:]", line.lstrip(), maxsplit=1)[0]
            skipping = key in values
        if not skipping:
            lines.append(line)
        skipping = skipping and (len(line) - len(line.rstrip("\\"))) % 2 == 1
    return "\n".join(lines) + "\n" + render_properties(values)


def content(parameters, name, fallback="", xml=False):
    values = section(parameters, name)
    if set(values) - {"content"}:
        raise ConfigurationError("This configuration type accepts only content: " + name)
    value = values.get("content", fallback)
    if xml:
        if "<!DOCTYPE" in value or "<!ENTITY" in value:
            raise ConfigurationError("External entities are not supported: " + name)
        try:
            ElementTree.fromstring(value)
        except ElementTree.ParseError:
            raise ConfigurationError("Invalid XML configuration: " + name)
    return value


def jvm_options(parameters, name, fallback):
    value = content(parameters, name, fallback)
    lines = []
    for line in value.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if (not line.startswith("-") or any(c.isspace() for c in line)
                or line.startswith(("-Xmx", "-Xms", "-XX:MaxRAM", "-XX:InitialRAM"))):
            raise ConfigurationError("Use one JVM option per line; heap belongs to basic settings: " + name)
        lines.append(line)
    return lines


def environment(parameters, name, managed=None):
    values = properties(parameters, name, managed)
    if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) for key in values):
        raise ConfigurationError("Environment variable names must be uppercase: " + name)
    return values


def shell_exports(values):
    return "".join("export " + key + "=" + shlex.quote(value) + "\n" for key, value in sorted(values.items()))


def yaml_properties(values):
    # JSON scalar/array notation is valid YAML and avoids implicit YAML coercions.
    result = []
    for key, value in sorted(values.items()):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        if parsed is None or isinstance(parsed, dict) or isinstance(parsed, float) and not (-float("inf") < parsed < float("inf")):
            raise ConfigurationError("Use a scalar or array for YAML property: " + key)
        result.append(json.dumps(key) + ": " + json.dumps(parsed, ensure_ascii=True, allow_nan=False))
    return "\n".join(result) + "\n"


def catalogs(parameters):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigurationError("Duplicate catalog or property")
            result[key] = value
        return result
    try:
        values = json.loads(content(parameters, "trino-catalogs", '{"tpch":{"connector.name":"tpch"}}'),
                            object_pairs_hook=unique)
    except ValueError:
        raise ConfigurationError("Catalogs must be a JSON object of catalog names and property objects")
    if not isinstance(values, dict) or len(values) > 128:
        raise ConfigurationError("Invalid catalog inventory")
    for name, props in values.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
            raise ConfigurationError("Invalid catalog name")
        validate_properties(props, "trino-catalogs")
        if not props.get("connector.name"):
            raise ConfigurationError("Each catalog requires connector.name")
    if values.get("tpch", {}).get("connector.name") != "tpch":
        raise ConfigurationError("The tpch catalog is required by the service check")
    return {name + ".properties": render_properties(props) for name, props in values.items()}
