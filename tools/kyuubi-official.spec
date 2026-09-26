# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

%global __os_install_post %{nil}
%global runtime /usr/bigtop/3.3.0/usr/lib/kyuubi
%global configuration /usr/bigtop/3.3.0/etc/kyuubi/conf.dist
Name: kyuubi_3_3_0
Version: 1.9.4
Release: 2.official.el8
Summary: Apache Kyuubi official binary distribution
License: ASL 2.0
URL: https://kyuubi.apache.org/
Source0: apache-kyuubi-1.9.4-bin.tgz
BuildArch: noarch
AutoReqProv: no
Requires: java-17-openjdk

%description
The unmodified Apache Kyuubi 1.9.4 binary distribution, packaged for the
BIGTOP 3.3.0 paths used by the Ambari Kyuubi reference management pack.

%prep
%setup -q -n apache-kyuubi-1.9.4-bin

%build
# The official binaries are reused without Maven, Gradle or frontend compilation.

%install
install -d %{buildroot}%{runtime} %{buildroot}%{configuration} %{buildroot}/etc/kyuubi
cp -a . %{buildroot}%{runtime}/
cp -a conf/. %{buildroot}%{configuration}/
rm -rf %{buildroot}%{runtime}/conf
ln -s /etc/kyuubi/conf %{buildroot}%{runtime}/conf
install -d %{buildroot}/var/lib/kyuubi %{buildroot}/var/log/kyuubi %{buildroot}/var/run/kyuubi

%pre
getent group kyuubi >/dev/null || groupadd -r kyuubi
getent passwd kyuubi >/dev/null || useradd -r -g kyuubi -d /var/lib/kyuubi -s /sbin/nologin kyuubi

%post
/usr/sbin/alternatives --install /etc/kyuubi/conf kyuubi-conf %{configuration} 30

%preun
if [ "$1" = 0 ]; then
  /usr/sbin/alternatives --remove kyuubi-conf %{configuration}
fi

%files
%defattr(-,root,root)
%{runtime}
%config(noreplace) %{configuration}
%dir /etc/kyuubi
%attr(0750,kyuubi,kyuubi) %dir /var/lib/kyuubi
%attr(0750,kyuubi,kyuubi) %dir /var/log/kyuubi
%attr(0750,kyuubi,kyuubi) %dir /var/run/kyuubi
