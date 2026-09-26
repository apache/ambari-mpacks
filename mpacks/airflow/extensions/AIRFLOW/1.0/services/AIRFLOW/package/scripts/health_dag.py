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

from datetime import datetime, timezone
from uuid import UUID

from airflow.sdk import dag, get_current_context, task


@dag(dag_id="ambari_mpack_health", schedule=None, catchup=False,
     start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
     is_paused_upon_creation=False, tags=["ambari-mpack-health"])
def health():
    @task
    def verify_execution():
        execution = get_current_context()["dag_run"].conf["execution_id"]
        if str(UUID(execution)) != execution:
            raise ValueError("Invalid health execution identity")
        return {"schema_version": 1, "execution_id": execution,
                "sum": sum(range(10)), "rows": len(range(10))}
    verify_execution()


health()
