# A 股投研 Agent — 部署文档

[English](DEPLOYMENT.md) | 简体中文

本文档说明系统在本地开发、本地完整运行与云端演示三种环境下的部署、配置、数据初始化、发布回滚、备份与故障排查。

相关文档:[技术架构文档](ARCHITECTURE.zh-CN.md) · [技术决策手册](TECH_DECISIONS.zh-CN.md)

> 本文档定义部署规范。各命令所依赖的组件随里程碑(架构文档 §23)逐步实现。

---

## 1. 环境总览

| 环境 | 用途 | 形态 | 对外暴露 |
|---|---|---|---|
| 本地开发 | 日常编码与调试 | 数据库与 Redis 用容器,api / worker / 前端以本地进程运行(支持热重载) | 仅本机 |
| 本地完整 | 集成验证、评测、故障注入 | `docker compose` 启动全部服务 | 仅本机 |
| 云端演示 | 公开演示与真实用户试用 | 单台云主机 + compose + Caddy | 仅 80 / 443 |

## 2. 服务清单

| 服务 | 镜像 | 端口(容器内) | 网络 | 持久化 |
|---|---|---|---|---|
| frontend | 自建(Nginx + 静态产物) | 80 | default | — |
| api | 自建(FastAPI / Uvicorn) | 8000 | default、sandbox_net | — |
| worker | 自建(复用 api 代码) | — | default、sandbox_net | — |
| sandbox-runner | 自建 | 8080 | sandbox_net(`internal: true`) | — |
| postgres | 自建(PostgreSQL 16 + pgvector + 中文分词扩展) | 5432 | default | `pgdata` |
| redis | redis:7 | 6379 | default | `redisdata`(AOF) |
| otel-collector | 官方镜像 | 4317 / 4318 | default | — |
| prometheus | 官方镜像(profile: obs) | 9090 | default | `prometheus_data` |
| grafana | 官方镜像(profile: obs) | 3000 | default | — |
| caddy | 官方镜像(仅云端) | 80 / 443 | default | `caddy_data` |

**postgres 需要自建镜像**:中文全文检索依赖中文分词扩展(zhparser 或 pg_jieba),官方 pgvector 镜像不包含。镜像构建见 `infra/postgres/Dockerfile`,构建后在初始化脚本中执行 `CREATE EXTENSION vector;` 与中文分词扩展的创建和文本搜索配置。

## 3. 前置条件

### 3.1 软件

| 软件 | 版本 | 用途 |
|---|---|---|
| Docker Engine | 24 及以上 | 运行容器 |
| Docker Compose | v2(`docker compose` 子命令) | 编排 |
| Python | 3.12 及以上 | 本地开发 |
| Node.js | 20 LTS 及以上 | 前端开发 |
| Git | 任意近期版本 | 代码管理 |

### 3.2 硬件

| 场景 | 最低 | 建议 |
|---|---|---|
| 本地开发 | 4 核 / 8 GB | 8 核 / 16 GB |
| 云端演示(嵌入与重排使用云端服务) | 2 核 / 4 GB | 4 核 / 8 GB |
| 云端演示(嵌入与重排模型自部署) | 4 核 / 16 GB | 8 核 / 32 GB,或配备 GPU |

嵌入与重排模型的选择见技术决策手册 D11。自部署模型对内存的要求明显更高,选型时须一并考虑。

### 3.3 外部服务

| 服务 | 是否必需 | 说明 |
|---|---|---|
| 模型服务 API Key | 必需(mock 模式除外) | 见 §5 地域与模型 |
| 域名 | 云端演示必需 | 用于 HTTPS 证书 |
| ICP 备案 | 域名解析到大陆服务器时必需 | 见 §5 |

## 4. 配置

所有配置通过环境变量注入,复制 `.env.example` 为 `.env` 后填写。`.env` 已被 `.gitignore` 排除,不得提交。

### 4.1 环境变量

| 变量 | 必填 | 说明 | 示例 |
|---|---|---|---|
| `APP_ENV` | 是 | `dev` / `local` / `prod`,控制日志格式、迁移策略等 | `dev` |
| `LLM_PROVIDER` | 是 | `mock` / `anthropic` / `openai_compat`。`mock` 返回预置响应,无需 API Key | `mock` |
| `ANTHROPIC_API_KEY` | 选填 | `LLM_PROVIDER=anthropic` 时必填 | — |
| `ANTHROPIC_MODEL` | 选填 | Anthropic 模型标识 | — |
| `OPENAI_COMPAT_BASE_URL` | 选填 | OpenAI 兼容接口地址 | DeepSeek:`https://api.deepseek.com`;通义千问:`https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `OPENAI_COMPAT_API_KEY` | 选填 | `LLM_PROVIDER=openai_compat` 时必填 | — |
| `OPENAI_COMPAT_MODEL` | 选填 | 模型标识 | `deepseek-chat`、`qwen-plus` |
| `DATABASE_URL` | 是 | PostgreSQL 连接串 | `postgresql+psycopg://app:***@postgres:5432/research` |
| `REDIS_URL` | 是 | Redis 连接串 | `redis://redis:6379/0` |
| `SANDBOX_URL` | 是 | sandbox-runner 地址 | `http://sandbox-runner:8080` |
| `JWT_SECRET` | 是 | 签发访问令牌的密钥,至少 32 字节随机值 | — |
| `DAILY_COST_LIMIT_USD` | 云端必填 | 全局日成本上限,超出后拒绝新任务 | `5` |
| `USER_DAILY_COST_LIMIT_USD` | 云端必填 | 单用户日成本上限 | `1` |
| `MAX_DEPTH` | 云端必填 | 允许的最大研究深度 | `standard` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 选填 | 追踪数据上报地址 | `http://otel-collector:4317` |
| `PIP_INDEX_URL` | 选填 | 大陆环境加速 Python 依赖安装 | 国内镜像源地址 |
| `NPM_REGISTRY` | 选填 | 大陆环境加速前端依赖安装 | 国内镜像源地址 |

档位到具体模型的映射、模型定价表、检索参数、预算配置在 `config/*.yaml` 中维护并纳入版本管理,不放在环境变量里。

### 4.2 密钥管理

- 密钥只存在于 `.env` 或云主机的环境中,不进入代码、镜像与日志。
- 日志与追踪对密钥字段脱敏。
- 云端 `.env` 文件权限设为 `600`,属主为部署用户。
- 更换密钥后重启相关服务,并在模型服务控制台吊销旧密钥。

## 5. 地域与模型

部署地域决定可用的模型服务与合规要求,须在部署前确定。

| | 部署在中国大陆 | 部署在境外 |
|---|---|---|
| 可用模型 | 国内可合规调用的模型(如通义千问、DeepSeek),`LLM_PROVIDER=openai_compat` | Anthropic 及境外模型服务;国内模型服务通常也可调用 |
| 不可用 | Anthropic 的模型服务不面向中国大陆提供 | — |
| 域名 | 解析到大陆服务器须完成 ICP 备案 | 无需备案 |
| 国内访问 | 速度与稳定性好 | 须实测,可能不稳定 |
| 镜像与依赖下载 | 建议配置 `PIP_INDEX_URL`、`NPM_REGISTRY` 与 Docker 镜像加速 | 无需 |

切换模型只需修改环境变量与 `config/models.yaml` 的档位映射。不同映射的效果差异应先用评测体系量化(实验 D),再决定部署配置。

## 6. 本地开发

```bash
# 1. 获取代码与配置
git clone <repo-url> && cd <repo>
cp .env.example .env              # 先保持 LLM_PROVIDER=mock

# 2. 启动数据库与 Redis
docker compose up -d postgres redis

# 3. 后端
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 4. worker(另开终端,在仓库根目录下)
cd worker && python -m app.consumer

# 5. sandbox-runner(另开终端,本地开发可直接以进程运行)
cd sandbox-runner && python -m app.main

# 6. 前端(另开终端)
cd frontend && npm install && npm run dev
```

本地开发时 sandbox-runner 以普通进程运行,没有容器隔离,只用于调试。涉及沙箱安全的验证必须在本地完整环境中进行。

## 7. 本地完整运行

```bash
docker compose up -d --build                  # 核心服务
docker compose --profile obs up -d            # 加上 Prometheus 与 Grafana
docker compose ps                             # 确认全部服务为 healthy
```

启动顺序由健康检查保证:api 与 worker 等待 postgres 与 redis 健康后才启动。api 的 `/readyz` 检查数据库连通性、Redis 连通性与数据库迁移版本。

**验证**

```bash
curl -f http://localhost:8000/healthz
curl -f http://localhost:8000/readyz
```

## 8. 数据初始化

首次部署或重建环境时按顺序执行。

### 8.1 数据库迁移

```bash
docker compose run --rm api alembic upgrade head
```

| `APP_ENV` | 启动时迁移版本不一致的行为 |
|---|---|
| `dev` / `local` | 自动升级 |
| `prod` | 拒绝启动,须在发布流程中显式执行迁移 |

### 8.2 数据摄取

```bash
# 标的主数据(含已退市标的)
docker compose run --rm worker python -m app.data.ingest securities

# 结构化财务数据(双时间轴,含修订版本)
docker compose run --rm worker python -m app.data.ingest fundamentals --symbols <代码列表> --years 2021-2024

# 年报与公告:下载、解析、分块、嵌入、建索引
docker compose run --rm worker python -m app.rag.ingest filings --symbols <代码列表> --years 2021-2024
```

- 摄取以 `content_hash` 去重,重复执行不产生重复数据,失败后可直接重跑。
- 摄取阶段执行财报勾稽校验,不满足的记录标记 `quality_flag`。
- 嵌入调用按量计费(使用云端嵌入服务时),首次全量摄取前先用一两家公司估算成本。
- 数据来源的使用条款须在公开部署前核对。

### 8.3 评测集与基线

```bash
harness run --suite factual --repeat 3
harness report --out docs/EVAL_REPORT.md
```

首次运行的结果作为基线存入 `harness/baselines/`。

## 9. 云端演示部署

### 9.1 主机准备

1. 按 §5 选择地域,按 §3.2 选择规格,系统盘建议 50 GB 以上。
2. 创建非 root 部署用户,只允许 SSH 密钥登录,关闭密码登录。
3. 防火墙(安全组)只放行 22(限定来源 IP)、80、443。数据库、Redis、Grafana 等端口不对外开放。
4. 安装 Docker Engine 与 Compose 插件,将部署用户加入 `docker` 组。
5. 域名解析 A 记录指向主机公网 IP;大陆主机须先完成备案。

### 9.2 部署

```bash
git clone <repo-url> && cd <repo>
cp .env.example .env && chmod 600 .env       # 填写生产配置,APP_ENV=prod

docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

`docker-compose.prod.yml` 相对开发配置的差异:

| 项 | 开发 | 云端 |
|---|---|---|
| 端口暴露 | 各服务直接暴露到本机 | 只有 caddy 暴露 80 / 443 |
| 重启策略 | `no` | `unless-stopped` |
| 资源限额 | 无 | 各服务设置 `mem_limit` |
| 日志 | 文本 | JSON,按大小轮转 |
| 数据库迁移 | 启动时自动 | 发布流程中显式执行 |
| 镜像 | 本地构建 | 按 commit SHA 打标签的镜像 |

### 9.3 反向代理

Caddy 是唯一对外入口,自动申请与续期 HTTPS 证书。

```
example.com {
    encode gzip

    handle /v1/* {
        reverse_proxy api:8000 {
            flush_interval -1
        }
    }

    handle {
        reverse_proxy frontend:80
    }
}
```

**SSE 必须关闭代理缓冲**:`flush_interval -1` 使响应立即转发。缺少这一项时,事件会被攒批发送,前端表现为长时间无响应后一次性刷出全部内容。若前端容器内的 Nginx 也代理 API 请求,需同时设置 `proxy_buffering off;`,或由 api 在 SSE 响应中返回 `X-Accel-Buffering: no` 头。

### 9.4 成本防护

无防护的公开 LLM 应用会在短时间内耗尽模型额度。云端环境必须同时启用以下措施:

| 措施 | 配置 |
|---|---|
| 强制登录 | 所有 `/v1/*` 接口要求有效令牌,不开放匿名访问 |
| 账号与 IP 双限流 | 每账号、每 IP 的请求速率与并发任务数上限 |
| 日成本熔断 | `DAILY_COST_LIMIT_USD`、`USER_DAILY_COST_LIMIT_USD`,超出后拒绝新任务 |
| 深度上限 | `MAX_DEPTH`,限制单次研究的 token 预算 |
| 模型服务侧额度 | 在模型服务控制台设置账户消费上限,作为最后一道防线 |

试用账号由管理员创建,不开放自助注册。

## 10. 发布与回滚

### 10.1 发布

```
PR 合并到 main
  → CI 通过(lint、类型检查、测试、评测门禁)
  → 构建镜像,标签为 commit SHA
  → 云主机拉取新镜像
  → 若有数据库迁移:先执行迁移
  → docker compose up -d(仅重建变更的服务)
  → 检查 /readyz 与关键页面
```

数据库迁移须向后兼容:新增字段先允许为空,删除字段分两次发布(先停止使用,再删除),使回滚到上一版本的代码时数据库仍可用。

### 10.2 回滚

```bash
# 将 .env 或 compose 文件中的镜像标签改回上一个 commit SHA
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

只在迁移不向后兼容时才回滚数据库,并须先从备份恢复演练确认可行。

### 10.3 优雅关闭

worker 收到 SIGTERM 后停止领取新任务,等待当前节点完成并写入检查点后退出。compose 中为 worker 设置足够的 `stop_grace_period`(不短于单节点超时)。未完成的任务由其他 worker 或重启后的 worker 从检查点恢复。

## 11. 备份与恢复

| 对象 | 方式 | 频率 | 保留 |
|---|---|---|---|
| PostgreSQL | `pg_dump` 逻辑备份,压缩后存到主机之外 | 每日 | 14 天 |
| Redis | AOF 持久化 | 持续 | — |
| `.env` 与配置 | 离线加密保存 | 变更时 | — |

```bash
# 备份
docker compose exec -T postgres pg_dump -U app -Fc research > backup_$(date +%F).dump

# 恢复(到空库)
docker compose exec -T postgres pg_restore -U app -d research --clean < backup_YYYY-MM-DD.dump
```

- Redis 中只有队列、缓存与限流状态,丢失后任务可由数据库中的 run 状态与检查点恢复,不依赖 Redis 备份。
- 至少每月做一次恢复演练:在独立环境中从备份恢复,并运行评测子集确认数据可用。

## 12. 监控与告警

启用 `obs` profile 后,Grafana 读取 Prometheus 指标。Grafana 不对外暴露,通过 SSH 隧道访问:

```bash
ssh -L 3000:localhost:3000 <user>@<host>
```

| 告警 | 条件 |
|---|---|
| 成本异常 | 单位时间成本超过基线倍数,或接近日成本上限 |
| 失败率上升 | run 失败率超过阈值 |
| 队列堆积 | `queue_depth` 持续超过阈值 |
| 延迟劣化 | 端到端 P95 超过阈值 |
| 重试激增 | `llm_retries_total` 增速异常,通常意味着模型服务故障或限流 |
| 检索结果不足 | `retrieval_short_results_total` 增速异常 |
| 磁盘 | 数据卷使用率超过 80% |

## 13. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 报告长时间无输出,最后一次性出现 | 代理缓冲了 SSE | 检查 Caddy 的 `flush_interval -1`,以及 Nginx 的 `proxy_buffering off` |
| 计算类问题全部失败,日志显示无法连接 sandbox | sandbox-runner 未接入 `sandbox_net`,或误用了 `network_mode: none` | 检查 compose 网络配置:api、worker 与 sandbox-runner 须同在 `sandbox_net` |
| 关键词检索几乎没有结果 | 数据库未安装中文分词扩展,或 tsvector 未使用中文配置生成 | 检查扩展是否存在;用中文配置重建 `tsv` 列与索引 |
| 指定单一标的时检索结果明显偏少 | 近似索引上的过滤召回不足 | 检查 `hnsw.iterative_scan` 是否启用;查看 `retrieval_short_results_total` |
| 模型调用连接超时或被拒绝 | 部署地域无法访问该模型服务 | 按 §5 切换到当地可用的模型服务 |
| 模型调用大量 429 | 触发模型服务限流 | 降低并发任务上限;检查全局重试预算是否生效 |
| api 启动失败,`/readyz` 报迁移版本不一致 | 生产环境未执行迁移 | 按 §8.1 显式执行迁移 |
| 任务一直停在 running | worker 失联且孤儿回收未触发 | 检查 worker 心跳与回收任务;查看 run 的恢复次数是否已达上限 |
| 当日新任务全部被拒绝 | 触发日成本熔断 | 查看成本面板确认是否为异常调用;确认无误后次日自动恢复 |

## 14. 上线检查清单

- [ ] 部署地域与模型服务匹配(§5),大陆主机已完成备案
- [ ] `.env` 完整,权限为 `600`,`APP_ENV=prod`,`LLM_PROVIDER` 不是 `mock`
- [ ] 安全组只放行 22(限定来源)、80、443
- [ ] 数据库迁移已执行,`/readyz` 返回正常
- [ ] HTTPS 证书签发成功
- [ ] SSE 流式输出在公网环境下逐段显示
- [ ] 成本防护全部启用(§9.4),模型服务控制台已设消费上限
- [ ] 沙箱无法访问外网(在沙箱中执行一次外网请求,确认失败)
- [ ] 每日备份任务已配置,并完成一次恢复演练
- [ ] 告警已配置并做过一次触发测试
- [ ] 留出集评测已在该部署配置下运行,结果记入评测报告
