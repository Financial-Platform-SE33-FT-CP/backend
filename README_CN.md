# 会计平台 — 后端单体仓库

uv workspace 单体仓库，包含所有后端微服务及共享库。

## 包列表

| 包名 | 说明 |
|------|------|
| `shared-lib` | 共享库：配置、数据库、中间件、异常、类型定义 |
| `auth-service` | 认证与权限控制 (US-1, US-3) |
| `tenant-service` | 多租户管理与科目表初始化 (US-2) |
| `coa-service` | 科目表管理 (US-4) |
| `ledger-service` | 日记账分录与试算平衡 (US-5, US-6) |
| `audit-service` | 审计日志 |
| `ar-ap-service` | 应收/应付管理 (US-8-12) |

## 开发

```bash
# 安装所有依赖
uv sync

# 启动指定服务
uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001

# 运行测试
uv run --package auth-service pytest

# 代码检查
uv run ruff check packages/
```

## 新增包

```bash
uv init --package packages/new-service
```

## 目录结构

```
backend/
├── pyproject.toml              # 工作区根配置
├── packages/
│   └── <service>/
│       ├── pyproject.toml
│       ├── src/<package_name>/
│       │   ├── main.py          # FastAPI 入口
│       │   ├── config.py        # 配置（pydantic-settings）
│       │   ├── deps.py          # 依赖注入
│       │   └── modules/<context>/
│       │       ├── domain/       # 领域层：实体、值对象、仓储接口
│       │       ├── application/  # 应用层：DTO、服务/命令处理器
│       │       ├── infrastructure/ # 基础设施层：ORM 模型、仓储实现
│       │       └── interfaces/api/ # 接口层：路由、请求/响应模型
│       ├── alembic/             # 数据库迁移
│       └── tests/               # 测试
```
