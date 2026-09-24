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

from resource_management.libraries.script.script import Script
from service import Kyuubi


class KyuubiClient(Script):
    def install(self, env):
        Kyuubi.install(self, env)

    def observe(self, action):
        return Kyuubi.observe(self, action)

    def configure(self, env):
        self.observe("configure_client")


if __name__ == "__main__":
    KyuubiClient().execute()
