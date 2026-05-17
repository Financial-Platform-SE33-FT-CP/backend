# Neon 数据库连接指南

## 概述

本项目使用 **Neon** 免费层云数据库替代本地 Docker PostgreSQL，所有团队成员共享同一个数据库实例，无需每人本地启动 PostgreSQL 容器。

- **Neon Console**: https://console.neon.tech
- **数据库名**: `neondb`
- **区域**: `ap-southeast-1` (AWS Singapore)

## 连接信息

```
Host:     <YOUR_NEON_HOST>
Port:     5432
Database: neondb
Username: <YOUR_NEON_USERNAME>
Password: <YOUR_NEON_PASSWORD>
SSL:      require
```

**SQLAlchemy 连接字符串 (asyncpg)**:
```
postgresql+asyncpg://<YOUR_NEON_USERNAME>:<YOUR_NEON_PASSWORD>@<YOUR_NEON_HOST>/neondb?ssl=require
```

## 如何用 pgAdmin 连接

1. 右键 **Servers → Register → Server**
2. **General 标签**: Name 随意填（如 `Neon - Accounting`）
3. **Connection 标签**:

   | 字段 | 值 |
   |------|-----|
   | Host name | `<YOUR_NEON_HOST>` |
   | Port | `5432` |
   | Maintenance database | `neondb` |
   | Username | `<YOUR_NEON_USERNAME>` |
   | Password | `<YOUR_NEON_PASSWORD>` |

4. **Parameters 标签**: SSL Mode 设为 `require`

## 如何运行数据库迁移(仅当数据库/表结构改变时使用)

迁移需要在 Docker 容器内通过 `uv run alembic` 执行。所有服务已配置好 Neon 连接（见 docker-compose.yml）。

```bash
# 在 infra 目录下执行，按依赖顺序：

# 1. auth-service（users 表）
docker compose -f docker/docker-compose.yml exec auth-service sh -c "cd packages/auth-service/alembic && uv run alembic upgrade head"

# 2. tenant-service（tenants、tenant_users 表）
docker compose -f docker/docker-compose.yml exec tenant-service sh -c "cd packages/tenant-service/alembic && uv run alembic upgrade head"

# 3. coa-service（chart_of_accounts 表）
docker compose -f docker/docker-compose.yml exec coa-service sh -c "cd packages/coa-service && uv run alembic upgrade head"

# 4. ledger-service（journal_entries、journal_entry_lines、accounting_periods 等）
docker compose -f docker/docker-compose.yml exec ledger-service sh -c "cd packages/ledger-service/alembic && uv run alembic upgrade head"

# 5. audit + ar-ap（如需要）
docker compose -f docker/docker-compose.yml exec audit-service sh -c "cd packages/audit-service/alembic && uv run alembic upgrade head"
docker compose -f docker/docker-compose.yml exec ar-ap-service sh -c "cd packages/ar-ap-service/alembic && uv run alembic upgrade head"
```

## 代码修改说明

`docker/docker-compose.yml` 中所有服务的 `DATABASE_URL` 已从本地 PostgreSQL 改为 Neon 连接串：

```yaml
# 之前
DATABASE_URL: postgresql+asyncpg://accounting:accounting_secret@postgres:5432/accounting

# 现在
DATABASE_URL: postgresql+asyncpg://<YOUR_NEON_USERNAME>:<YOUR_NEON_PASSWORD>@<YOUR_NEON_HOST>/neondb?ssl=require
```

同时修复了：
- `docker/frontend/Dockerfile`: `npm ci` → `npm install`（适配缺少 lockfile）
- `nginx/default.conf` 挂载路径: `./nginx/` → `../nginx/`

## 已存在的测试数据

| 表 | ID | 说明 |
|------|-----|------|
| users | `11111111-1111-1111-1111-111111111111` | 测试用户 |
| tenants | `11111111-1111-1111-1111-111111111111` | 测试租户 |
| chart_of_accounts | `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa` | 科目 1000 — Cash at Bank |
| chart_of_accounts | `bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb` | 科目 5000 — Sales Revenue |
| accounting_periods | (随机 UUID) | 2026-05 期间，未关闭 |

## Schema 变更规则

1. 所有表结构变更通过 **Alembic migration** 进行，禁止直接在 Neon 上 `ALTER TABLE`
2. 新建 migration: `alembic revision -m "your_description"`，编写 `upgrade()` 和 `downgrade()`
3. Migration 文件随代码通过 PR 提交
4. PR 合并后由一人（Tech Lead）在 Neon 上执行 `alembic upgrade head`
5. 其他成员不需要本地跑 migration，连接云库即可开发

## 常见问题

**Q: 连接时提示 `ssl` 错误？**
A: asyncpg 使用 `?ssl=require` 而非 `?sslmode=require`。连接字符串末尾确保是 `?ssl=require`。

**Q: 免费层够用吗？**
A: Neon 免费层 0.5GB 存储，对课程项目开发阶段足够。

**Q: 想切换回本地开发怎么办？**
A: 在 docker-compose 中将 `DATABASE_URL` 改回本地 PostgreSQL 连接串，并取消注释 `postgres` 服务。
