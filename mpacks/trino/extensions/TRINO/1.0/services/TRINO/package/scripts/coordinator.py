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

from managed_service_v2 import ManagedServiceV2


class Coordinator(ManagedServiceV2):
    service = "trino"
    component = "coordinator"
    topology_fields = {"coordinator_host": ("trino_coordinator_hosts", True, False),
                       "worker_hosts": ("trino_worker_hosts", False, True)}


if __name__ == "__main__":
    Coordinator().execute()
