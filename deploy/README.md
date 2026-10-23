# Railway 自动部署

部署源为私有仓库 `Merry-Q/offerOS` 的 `main` 分支。当前 FastAPI、SQLite 和后台线程需要持续运行的服务及持久卷。

## 服务配置

1. 在 Railway 新建项目，选择 Deploy from GitHub repo，连接 `Merry-Q/offerOS`，分支选择 `main`。GitHub App 仅授权此仓库即可。
2. 保留仓库根目录，使用自动识别的 Dockerfile。`railway.json` 配置 `/api/healthz` 健康检查和失败重启策略。启用 GitHub 自动部署及 Wait for CI，后续推送通过 Checks 后自动发布。
3. 为应用挂载一个 Volume，路径为 `/var/lib/offeros`；保持单副本、关闭按闲置自动休眠。SQLite、上传文件及搜索历史只写入此目录。
4. 设置运行变量，密钥只能放在 Railway Variables，不能提交 `.env`：

   | 变量 | 设置 |
   | --- | --- |
   | `RAILWAY_RUN_UID` | `0`，用于初始化平台挂载卷的权限；启动程序随后降权为 UID 10001 |
   | `OFFEROS_DATA_DIR` | `/var/lib/offeros` |
   | `ENVIRONMENT` | `production` |
   | `DISABLE_DOCS` | `true` |
   | `LLM_MODE` | `auto` |
   | `DASHSCOPE_API_KEY` | 在控制台填写真实百炼密钥 |
   | `ADMIN_USERNAME` | 自定管理员名称 |
   | `ADMIN_PASSWORD` | 至少12位独立密码，不能使用示例值 |
   | `CORS_ORIGINS` | 生成公网域名后填写对应的 `https://…` 来源 |

   百炼地域端点和模型名称沿用 `.env.example`，有自定义工作空间时在 Variables 中覆盖。不要上传本地 `.env`。`PORT` 由平台设置，启动程序自动读取，无需写死端口。

5. Generate Domain 时使用平台分配的监听端口，Railway提供HTTPS。发布后验收首页、`/api/healthz`、虚构档案、独立上传空间、岗位搜索与历史翻页、长报告及管理员登录。

## 验证和数据

GitHub Actions运行隐私文件扫描、Python及JavaScript测试，并构建容器，在动态端口和挂载卷下检查健康探针。本机没有Docker，实际镜像运行以该CI及Railway部署结果为准。

`python scripts/check_publish.py` 检查Git候选路径和常见密钥格式；它不能证明不存在所有形式的个人信息，因此提交前仍需核对文件清单。Docker构建仅包含 `server/`、`static/` 和依赖表。示例人物及测试数据均为虚构；本地真实简历、会话和历史数据库不会迁移到公网环境。

版本更新保留挂载卷；不要删除卷来重建部署。迁移既有数据需先备份并停写，使用SQLite backup接口导出数据库、复制上传文件，以UID 10001写入新卷。模型调用尚无按访客的每日配额，公开演示前应在百炼控制台设置用量预算。

运行服务和HTTPS地址是否可用，须以Railway的成功部署和公网访问验收为准；仅推送代码不等同于上线完成。
