# 阿里云 ECS 部署

部署日期：2026-10-26（北京时间）。

- 产品入口：https://offeros.47.237.109.221.sslip.io/
- 管理入口：https://offeros.47.237.109.221.sslip.io/admin/login
- 健康检查：https://offeros.47.237.109.221.sslip.io/api/healthz
- 应用目录：`/opt/offeros`
- 数据库与上传文件：`/opt/offeros/data`
- 运行变量：`/opt/offeros/.env.production`，权限 600
- 本机初始化凭据：项目根目录 `.env.aliyun`，已被 Git 排除。用户名为 `admin`，独立随机密码见其中 `ADMIN_PASSWORD`。首次登录后在管理端改密；初始化文件不会自动同步改密后的密码。

部署只传输服务代码、静态资源和必要配置。公网数据库由虚构示例初始化，不复制本机真实简历、会话、历史数据库或无关服务密钥。百炼密钥通过 SSH 单独传输，在服务器运行时注入，不进入镜像。

## 运行结构

现有 1Panel OpenResty 接收 80/443 请求，并以主机名 `offeros.47.237.109.221.sslip.io` 转发到 `127.0.0.1:18000`。服务器 IP 根路径改由个人主页占用；旧的 `/admin`、`/api/`、`/login` 会 308 到本子域名。新增配置位于 `/opt/1panel/apps/openresty/openresty/conf/conf.d/offeros.conf`，对应本目录的 `offeros.nginx.conf`。应用端口只监听服务器回环地址，无需新增安全组端口。

`compose.aliyun.yaml` 启动单进程 FastAPI，使用非 root 身份、只读容器文件系统和独立数据目录。容器配置自动重启、健康检查、320 MB 内存上限及日志轮转。代理对 API 和密码登录分别限速。数据库目录属于 UID/GID 10001；应用目录属于 root，权限 700。

服务器 Docker 默认桥接网段 `172.17.0.0/16` 与 ECS 内网 `172.17.0.0/18` 重叠，导致该默认网络无法正常访问 DNS。构建使用 host 网络；运行容器使用独立 Compose 网络（本次分配 `172.19.0.0/16`），已验证容器内实际模型调用。没有改动服务器全局 Docker 网络或重启既有服务。

当前入口使用 HTTPS。`CORS_ORIGINS` 须包含 `https://offeros.47.237.109.221.sslip.io`。正式收集真实简历前仍应换成自有域名，并核对证书与来源配置。

## 查看状态与日志

以下命令在服务器执行：

```sh
cd /opt/offeros
docker compose -p offeros -f deploy/compose.aliyun.yaml ps
docker compose -p offeros -f deploy/compose.aliyun.yaml logs --tail 100
curl -fsS http://127.0.0.1:18000/api/healthz
```

## 更新与回退

更新前先备份数据和当前镜像。只更新 `server/`、`static/`、依赖表及部署文件，保留 `.env.production` 和 `data/`。不要从本机覆盖服务器数据库。

```sh
cd /opt/offeros
docker tag offeros:latest offeros:previous
docker compose -p offeros -f deploy/compose.aliyun.yaml build
docker compose -p offeros -f deploy/compose.aliyun.yaml up -d --wait --wait-timeout 60
curl -fsS http://127.0.0.1:18000/api/healthz
```

本次首发镜像另存为 `offeros:20261026-1`。需要回退应用时：

```sh
cd /opt/offeros
OFFEROS_RELEASE=20261026-1 docker compose -p offeros -f deploy/compose.aliyun.yaml up -d --no-build --wait
```

回退镜像不会回退数据库结构；未来若包含数据库迁移，需同时评估备份恢复。

## 备份数据

短暂停写后打包数据目录，确保数据库和上传文件属于同一备份点。命令保留运行配置文件，不打印其中密钥：

```sh
cd /opt/offeros
umask 077
backup_name="data-$(date +%Y%m%d-%H%M%S).tar.gz"
docker compose -p offeros -f deploy/compose.aliyun.yaml stop
trap 'docker compose -p offeros -f deploy/compose.aliyun.yaml start' EXIT
tar -czf "backups/$backup_name" -C data .
docker compose -p offeros -f deploy/compose.aliyun.yaml start
trap - EXIT
```

备份保存在同一服务器，只防止误操作；如需抵御整机故障，应另存到独立存储。

## 验收记录

- 本地 58 项 Python 测试、4 项 JavaScript 测试通过，发布文件扫描通过。
- 公网首页、静态资源、管理员登录页与健康检查返回 200。
- 虚构档案、四份岗位和示例长报告读取正常。
- 独立访客上传、解析和跨身份访问隔离检查通过。
- 管理员登录与分析指标接口正常，首位管理员注册已关闭。
- 容器内真实 `qwen-flash` 请求成功。
- 强制重建容器后检查访客会话和上传持久化；完成后删除合成测试简历。
- `/docs`、`/openapi.json`、环境配置和数据库文件路径未公开。

这些检查不保证外部招聘网站始终可抓取，也不代表本次进行了完整的真实岗位搜索和新长报告生成。
