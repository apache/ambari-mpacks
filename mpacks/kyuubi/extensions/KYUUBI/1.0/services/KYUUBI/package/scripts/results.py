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


def validate_result(request, result, allow_unresolved=False):
    """Validate lineage before preserving either success or failure evidence."""
    if not isinstance(result, dict):
        raise ValueError("Service observation must be an object")
    for key in ("schema_version", "definition_snapshot", "execution_id", "task_id", "action"):
        if key not in result or type(result[key]) is not type(request[key]) or result[key] != request[key]:
            raise ValueError("Service observation is missing or belongs to another execution")
    outcomes = {"APPLIED", "UNRESOLVED"} if allow_unresolved else {"APPLIED"}
    if result.get("outcome") not in outcomes or not isinstance(result.get("observations"), dict) or not result["observations"]:
        raise ValueError("Service action has no verified structured observations")
    return result
