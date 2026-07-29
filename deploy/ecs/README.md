# ECS 部署说明

目标机：`/opt/IgniteQuant`（阿里云 Ubuntu）

## 日常发布（本机执行）

在项目根目录 `.env` 增加（勿提交）：

```bash
ECS_HOST=8.159.133.212
ECS_USER=root
ECS_PASSWORD=你的SSH密码
# 或改用密钥：
# ECS_SSH_KEY=C:/Users/你/.ssh/id_ed25519_ecs
```

```bash
# 同步当前工作区到 ECS（可含未提交改动），重建前端，重启 API
python tools/deploy_to_ecs.py

# 策略/模拟相关改动再加：
python tools/deploy_to_ecs.py --restart-sim

# 已 commit + push 时，也可用 Git 硬同步：
python tools/deploy_to_ecs.py --via-git --restart-sim
```

脚本**不会**覆盖服务器上的：

- `.env`
- `data/runtime/*.sqlite`（及 wal/shm）

## 仅把服务器目录挂上 GitHub

```bash
python tools/deploy_to_ecs.py --setup-git-only
```

远程：`https://github.com/hawk1949-rs/IgniteQuant.git`（`master`）
