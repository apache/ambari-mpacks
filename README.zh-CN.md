<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements. See the NOTICE file
distributed with this work for additional information
regarding copyright ownership. The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License. You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Ambari 第三方管理包

[English](README.md) | 简体中文

本仓库存放独立版本化的 Apache Ambari 第三方管理包，包括服务定义、配置模板和
运行时安装脚本。管理包的制作工具和 HTTP 客户端 `ambari-mpack` 位于 Ambari 核心
仓库。管理包描述 Ambari 如何管理服务；**导入管理包不会在主机上安装该服务**。

## 适用范围

目前的基础验收目标是使用 systemd 的 Rocky Linux 8/aarch64。仓库保留了 Ubuntu
定义，但本轮验收没有覆盖 Ubuntu。各组件 README 和
[验收记录](docs/five-component-implementation.md)列出已测版本、主机前提、拓扑
限制和仍待解决的安全能力。基础验收不等于生产环境或高可用认证。

完整商店包含一个共享包和十个服务包：

| 管理包 | 用途及重要前提 | 详细说明 |
| --- | --- | --- |
| `generic-base` | 服务包共用的定义 | [目录](mpacks/generic-base/) |
| `nginx` | 使用操作系统软件包管理 Nginx，不依赖 Hadoop 或 stack-select | [目录](mpacks/nginx/) |
| `postgresql` | 使用操作系统软件包管理 PostgreSQL，不依赖 Hadoop 或 stack-select | [目录](mpacks/postgresql/) |
| `kyuubi` | 扩展 BIGTOP 的 Spark、Hadoop 和 ZooKeeper 环境 | [README](mpacks/kyuubi/README.md) |
| `airflow` | 独立 Python 环境及外部 PostgreSQL 14-18 数据库 | [README](mpacks/airflow/README.md) |
| `celeborn` | 固定版本的官方二进制包；基础单 Master 拓扑 | [README](mpacks/celeborn/README.md) |
| `dolphinscheduler` | 独立的运行时与配置 | [README](mpacks/dolphinscheduler/README.md) |
| `trino` | 独立的运行时与配置 | [README](mpacks/trino/README.md) |
| `doris` | 独立的运行时与配置 | [README](mpacks/doris/README.md) |
| `elasticsearch` | 独立的运行时与配置 | [README](mpacks/elasticsearch/README.md) |
| `minio` | 固定的源码构建，不是早期仅含定义的草案 | [README](mpacks/minio/README.md) |

`release.json` 是管理包路径和**精确管理定义版本**的权威索引。这些版本不代表主机
上已安装软件的版本。需要较小的交付包时，`profiles/infrastructure.json` 只选择
`generic-base`、`nginx` 和 `postgresql`。`tooling.lock` 记录匹配的制作工具及
manifest schema 版本。

## 构建完整商店

在隔离环境中使用 Python 3.10 或更新版本，从兼容的 Ambari 核心源码安装
`ambari-mpack`。选择工具版本前先核对 `tooling.lock`。以下命令假定已激活
Python 虚拟环境：

```sh
python3 -m pip install /path/to/ambari/dev-support/mpack
ambari-mpack --help
```

在本仓库根目录校验单个管理包，并按 `release.json` 构建所有当前版本：

```sh
ambari-mpack --json validate mpacks/nginx
ambari-mpack --json build --all --repository . --output dist --bundle mpackstore
```

构建结果包括 `dist/` 下独立版本的管理包归档，以及用于交付的
`dist/mpackstore.bundle.tar.gz`。分发时保持 bundle 完整。如只需基础设施包，
将 `--all` 换成 `--profile infrastructure` 并使用不同的 bundle 名称；如需指定
包，改用 `--packs generic-base,nginx,postgresql`。bundle 应包含全部必要依赖，
除非目标 Server 已导入这些依赖。这些选择方式都读取 `release.json` 中的
精确版本。构建 bundle 不会连接 Ambari Server。

## 导入并选择服务

目标 Ambari Server 必须支持 HTTP Management Packs API。在 Ambari 界面打开
**Management Packs**，上传 `dist/mpackstore.bundle.tar.gz`，选择
**Import Packages**。导入只注册商店中的包，不启用定义，也不运行包的 hook。
随后在 **Available Services** 中选择所需服务，指定新集群或兼容的现有集群。
Server 会解析必要的 provider 包和扩展绑定；选择一个服务不会部署 bundle 中的
全部服务。

也可以使用只通过 HTTP 与 Server 通信的 CLI：

```sh
ambari-mpack --server "$AMBARI_SERVER_URL" import dist/mpackstore.bundle.tar.gz
ambari-mpack --server "$AMBARI_SERVER_URL" services
```

执行前把 `AMBARI_SERVER_URL` 设为目标 Server 地址。使用私有 CA 的 HTTPS
连接应给 CLI 传入 `--ca-file`。交互式终端会安全提示输入 Ambari 密码；不要把密码
写在命令行或仓库文件中。自动化调用应通过受保护的环境或
密钥存储提供 `AMBARI_PASSWORD`。默认情况下，导入命令会等待操作结束。保存返回的
精确 operation ID；需要诊断时执行
`ambari-mpack --server "$AMBARI_SERVER_URL" operations show OPERATION_ID`。
若提交过程被中断，可使用 `operations resume SUBMISSION_ID` 恢复；不能仅凭
上传成功就认定导入完成。

## 配置、更新和恢复

[配置文件指南](docs/content-configuration.md)说明十项服务的完整内容编辑器，以及
原有标量配置的迁移行为。用户已保存的完整内容不会从包默认值静默重建。导入新版本
不会自动替换正在使用的定义，也不会升级主机软件；激活与部署是独立操作。定义变更
时应发布新的包版本并更新 `release.json`，不要覆盖已有版本的归档。

在线激活阶段执行的包 hook 必须声明 `scope: "DEFINITIONS"`，并遵守包的资源边界；
这一声明并不能隔离任意代码。PostgreSQL 参考实现的 BACKUP 会生成经过校验、关联
具体操作的归档；RESTORE 要求指定隔离目标，不会覆盖源数据库。它不提供自动故障
转移、多实例身份管理或任意前端插件。

本仓库的命令不会直接修改 Ambari Server 的文件系统或数据库。软件来源应通过
Ambari 仓库记录配置；验收结果应以权威操作状态和 Service Check 为准。

## 仓库导航

- `mpacks/`：版本化管理定义和组件各自的 README。
- `shared/`：由包声明引用的共享运行时辅助代码。
- `release.json`、`profiles/`、`tooling.lock`：版本选择和工具契约。
- `docs/content-configuration.md`：配置内容编辑与迁移。
- `docs/component-expansion-results.md` 和
  `docs/five-component-implementation.md`：验收证据与限制。
- `docs/component-expansion-plan.md`：SeaTunnel、Superset、Iceberg catalog 等
  潜在后续服务。

贡献者可运行 `python3 -m unittest discover -s tests -v` 检查本仓库的针对性测试。
增加服务时，不应顺带重复提供已有 BIGTOP 服务的 provider。
