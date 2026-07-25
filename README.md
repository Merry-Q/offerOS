# OfferOS

个人求职匹配引擎（FastAPI + SQLite）。

主链路：**简历库 → JD 截图/文本 → 综合判分 → 六模块报告 → 匹配库**。另含用户注册/登录与管理端埋点看板。

## 快速开始

```powershell
cd offerOS
python -m pip install -r requirements.txt
copy .env.example .env
# 编辑 .env：填入 GLM_API_KEY（可选）；务必修改 ADMIN_PASSWORD
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

打开：

| 入口 | 地址 |
|------|------|
| 用户登录 | http://127.0.0.1:8000/login |
| 用户注册 | http://127.0.0.1:8000/register |
| 产品 | http://127.0.0.1:8000/（需登录） |
| 管理端登录 | http://127.0.0.1:8000/admin/login |
| 管理端 | http://127.0.0.1:8000/admin（需管理员） |

默认管理员由 `.env` 自动初始化（`ADMIN_USERNAME` / `ADMIN_PASSWORD`）。若仍使用环境默认口令，登录后会提示改密。  
若库中尚无管理员，可在 `/admin/register` 创建首位管理员（仅一次）。

## 环境变量（`.env`）

| 变量 | 说明 |
|------|------|
| `GLM_API_KEY` | 大模型 Key（**仅后端**） |
| `GLM_BASE_URL` | 默认 `https://api.z.ai/api/paas/v4` |
| `GLM_MODEL` | 默认 `glm-5.2` |
| `GLM_VISION_MODEL` | JD 截图识图模型，默认 `glm-5v-turbo` |
| `LLM_MODE` | `auto` / `mock` / `glm` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 启动时若不存在则创建管理员；请用强密码 |
| `AUTH_SECRET` | 预留密钥（建议更换） |
| `ENVIRONMENT` | `development` / `production`（production 默认关 docs） |
| `DISABLE_DOCS` | `true` / `false`，覆盖文档开关 |
| `CORS_ORIGINS` | 逗号分隔来源；同域可用 `*` |
| `MAX_UPLOAD_MB` | 上传上限（MB），默认 `5` |

**切勿**将 `.env` 或 `data/` 提交到 Git。

## 产品能力

1. **建库引导**：上传 PDF/DOCX 简历 → Resume Analyst 画像（至少 1 份已解析即可完成建库）
2. **个人职业库**：多简历 CRUD；库内解析（带进度反馈）
3. **JD 匹配**：粘贴/上传 JD 截图自动识别（可编辑文本兜底）→ 选简历画像 → JD 解析 → 综合判分（胜任 40% + 证明 25% + 竞争 35%）→ 六模块报告
4. **匹配库**：历史岗位与多版本；重新匹配追加版本
5. **管理端**：时间窗指标、新客/回访双漏斗、匹配质量与用量趋势
6. **账户**：用户注册/登录/改密/登出；管理员登录/改密

## 目录

```
server/     FastAPI 应用、鉴权、Agent
static/     产品页与管理端
data/       SQLite 与上传文件（运行后生成，已 gitignore）
```
