# OfferOS

个人求职匹配引擎（FastAPI + SQLite）。

两条主链路：**简历 → 职业画像 → 适投方向 → 模拟面试**，以及 **岗位截图/网页/JD → 背调与岗位解析 → 四维匹配 → 简历与面试准备**。公开站点默认进入虚构人物 Demo，无需登录注册。

## 在线访问

当前已部署环境：

| 入口 | 地址 |
|------|------|
| 公开 Demo | http://123.56.217.207/（无需登录） |
| 管理端登录 | http://123.56.217.207/admin/login |
| 管理端 | http://123.56.217.207/admin（需管理员） |

`/login` 与 `/register` 会跳转到产品 Demo。

## 本地开发

```powershell
cd offerOS
python -m pip install -r requirements.txt
copy .env.example .env
# 编辑 .env：填入 GLM_API_KEY（可选）；务必修改 ADMIN_PASSWORD
python -m uvicorn server.main:app --reload
```

启动后，浏览器访问路径与「在线访问」表一致（将主机替换为你的运行环境即可）。打开首页会自动进入虚构人物 Demo，无需登录。

默认管理员由 `.env` 自动初始化（`ADMIN_USERNAME` / `ADMIN_PASSWORD`）。若仍使用环境默认口令，登录后会提示改密。

公开 Demo 由启动时自动写入：虚构人物「林知夏」、四份岗位分析（保 / 冲 / 稳 / 不建议投）。运行 `python scripts/seed_demo.py` 可重置这些演示数据。
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

1. **职业档案**：解析 PDF / Word，形成知识技能、工作经验、核心能力、个性特质四维画像，并允许标注式补充简历外能力。
2. **适投方向与面试**：依据画像生成适合职位/行业、个性化题库、浏览器实时语音转写和面试复盘报告。
3. **统一岗位输入**：同一岗位多张截图连续粘贴并自动合并，也支持网页链接和 JD 文本；长图保留文字宽度并分片 OCR。
4. **岗位证据**：提取公司、地点、招聘类型、专业/学历/经验/语言硬门槛、加分项与核心能力。
5. **公司与行业背调**：检索近半年业务动作、融资和估值；事实结论必须绑定原始来源，检索不到时明确说明。
6. **四维匹配**：35% 知识技能 + 25% 工作经验 + 25% 核心能力 + 15% 个性特质；硬门槛只警示，不篡改原分和保稳冲档位。
7. **行动建议**：同方向岗位提供句子润色，跨岗位/行业提供项目级改写，并生成岗位面试准备内容。
8. **历史分析与管理端**：保留完整分析结果；管理端提供漏斗、质量和用量指标。
9. **账户与 Demo**：公开站点自动进入虚构演示账号，无需注册登录；管理端仍需管理员账号。

## 目录

```
server/     FastAPI 应用、鉴权、Agent
static/     产品页与管理端
data/       SQLite 与上传文件（运行后生成，已 gitignore）
```
