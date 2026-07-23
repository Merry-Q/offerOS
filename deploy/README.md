# 国内轻量云部署手册（阿里云）

面向：Ubuntu 22.04 轻量应用服务器，单机 SQLite，1 个 uvicorn worker。

## 0. 准备

- 已将代码推送到 GitHub 私有仓库
- 服务器安全组开放：22、80、443
- 本机可用 SSH 登录
- 域名可稍后；备案完成前可用公网 IP 试用

## 1. 服务器初始化

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
sudo mkdir -p /opt/offeros
sudo chown "$USER":"$USER" /opt/offeros
cd /opt/offeros
git clone https://github.com/Merry-Q/offerOS.git .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # 填入强密码、GLM_API_KEY、ENVIRONMENT=production
```

生产 `.env` 关键项建议：

```env
ENVIRONMENT=production
DISABLE_DOCS=true
CORS_ORIGINS=*
ADMIN_PASSWORD=<强密码>
AUTH_SECRET=<长随机串>
GLM_API_KEY=<你的Key>
LLM_MODE=auto
MAX_UPLOAD_MB=5
```

## 2. systemd 常驻

```bash
sudo cp deploy/offeros.service /etc/systemd/system/offeros.service
# 若运行用户不是 www-data，请编辑 User/Group 与目录权限
sudo mkdir -p /opt/offeros/data/uploads /opt/offeros/backups
sudo chown -R www-data:www-data /opt/offeros
sudo systemctl daemon-reload
sudo systemctl enable --now offeros
sudo systemctl status offeros
curl -s http://127.0.0.1:8000/api/healthz
```

## 3. nginx 反代

```bash
sudo cp deploy/nginx.offeros.conf /etc/nginx/sites-available/offeros
# 编辑 server_name：域名或先用 _
sudo ln -sf /etc/nginx/sites-available/offeros /etc/nginx/sites-enabled/offeros
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

浏览器访问：`http://<公网IP>/login`

## 4. 域名 + HTTPS（备案通过后）

1. 域名解析到服务器公网 IP  
2. 修改 nginx `server_name`  
3. 安装证书（示例 Let’s Encrypt；部分国内环境用云厂商免费证书更方便）：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your.domain.com
```

4. 将 `CORS_ORIGINS` 改为你的 `https://域名`（可选收紧）并重启：

```bash
sudo systemctl restart offeros
```

## 5. 每日备份

```bash
sudo chmod +x /opt/offeros/deploy/backup.sh
sudo crontab -e
# 每天 3:00
0 3 * * * APP_DIR=/opt/offeros /opt/offeros/deploy/backup.sh >> /var/log/offeros-backup.log 2>&1
```

## 6. 更新代码

```bash
cd /opt/offeros
sudo -u www-data git pull   # 或你的部署用户
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart offeros
```

## 7. 验收

- 用户注册 / 登录 / 改密  
- 上传简历 → JD 匹配 → 六模块报告 → 匹配库  
- `/docs` 在生产应 404  
- `/api/healthz` 返回 `{"ok": true}`  
- 管理端需管理员登录  
