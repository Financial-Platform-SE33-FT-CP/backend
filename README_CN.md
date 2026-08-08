# 会计平台 — 后端单体仓库

uv workspace 单体仓库，包含 8 个后端微服务及共享库。

## 包列表

| 包名 | 说明 |
|------|------|
| `shared-lib` | 共享库：配置、数据库、中间件、异常、类型定义、RBAC、套餐方案 |
| `auth-service` | 认证与权限控制 (US-1, US-3) |
| `tenant-service` | 多租户管理与科目表初始化 (US-2) |
| `coa-service` | 科目表管理 (US-4) |
| `ledger-service` | 日记账分录与试算平衡 (US-5, US-6) |
| `audit-service` | 审计日志 |
| `ar-ap-service` | 应收/应付管理 (US-8-12) |
| `billing-service` | Stripe 支付、Webhook、套餐管理 |

## 快速开始

```bash
# 安装所有依赖
uv sync

# 启动 PostgreSQL（需要 Docker）
docker compose up -d

# 运行数据库迁移
.\scripts\dev-migrate.ps1   # Windows
# 或手动执行：
uv run --package auth-service alembic upgrade head

# 启动服务
uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001
```

## 开发

```bash
# 启动指定服务
uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001

# 运行测试
uv run --package auth-service pytest

# 带覆盖率运行测试
uv run --package auth-service pytest --cov=auth_service

# 代码检查与格式化
uv run ruff check packages/
uv run ruff format packages/

# 类型检查
uv run mypy packages/

# 生成数据库迁移
```

## 服务端口

| 服务 | 端口 | 健康检查 |
|------|------|----------|
| auth-service | 8001 | `/health` |
| tenant-service | 8002 | `/health` |
| ledger-service | 8003 | `/health` |
| coa-service | 8004 | `/health` |
| audit-service | 8005 | `/health` |
| ar-ap-service | 8006 | `/health` |
| billing-service | 8007 | `/health` |
| PostgreSQL | 5432 | — |

## CI/CD

- **CI**：各服务独立工作流，push/PR 到 `develop` 时运行 lint + 类型检查 + 单元测试 + 集成测试。
- **CD**：多服务 Docker 构建矩阵，推送至 `ghcr.io/financial-platform-se33-ft-cp/accounting-platform-{service}`。
- **Release**：标签触发（`v*`）GitHub Release，自动生成变更日志。

## 架构

所有服务遵循领域驱动设计（DDD）：

```
packages/<service>/
├── pyproject.toml
├── alembic/                  # 数据库迁移（每服务独立 version_table）
├── src/<package_name>/
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 配置（pydantic-settings）
│   ├── deps.py               # 依赖注入
│   └── modules/<context>/
│       ├── domain/            # 领域层：实体、值对象、仓储接口
│       ├── application/       # 应用层：DTO、服务/命令处理器
│       ├── infrastructure/    # 基础设施层：ORM 模型、仓储实现
│       └── interfaces/api/    # 接口层：路由、请求/响应模型
└── tests/
    ├── conftest.py
    ├── unit/
    └── integration/
```

## 新增包

```bash
uv init --package packages/new-service
```

添加 `shared-lib` 依赖，参照现有服务的 DDD 分层模式即可。
