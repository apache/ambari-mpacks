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

from managed_runtime import host_value


def assigned_hosts(parameters, topology, fields):
    result = dict(parameters)
    for field, (component_key, single, optional) in fields.items():
        assigned = topology.get(component_key, [] if optional else None)
        if not isinstance(assigned, (list, tuple)) or any(not isinstance(host, str) for host in assigned):
            raise ValueError("Missing component assignment: " + component_key)
        hosts = sorted(host_value(host) for host in assigned)
        if len(hosts) != len(set(hosts)) or (not hosts and not optional) or (single and len(hosts) != 1):
            raise ValueError("Invalid component assignment: " + component_key)
        configured = result.get(field)
        selected = hosts[0] if single else ",".join(hosts)
        if configured and configured != selected:
            raise ValueError("Configured topology differs from assigned hosts: " + field)
        result[field] = selected
    return result
