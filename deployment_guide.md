# OurDaily.ai 部署指南

本文档提供了OurDaily.ai网站的详细部署指南，包括端云协同功能和一键部署能力。

## 1. 系统要求

### 服务器端
- 操作系统：Ubuntu 20.04 LTS或更高版本
- Python 3.8+
- Node.js 14+
- Nginx
- 至少2GB RAM和10GB存储空间

### 客户端（用户设备）
- Windows 10/11 64位或macOS 11.0+
- 至少4GB RAM
- 支持现代浏览器（Chrome, Firefox, Safari, Edge）

## 2. 部署步骤

### 2.1 准备环境

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装依赖
sudo apt install -y python3-pip python3-venv nginx

# 创建应用目录
mkdir -p /var/www/ourdaily
```

### 2.2 解压文件

```bash
# 解压web8.tar到应用目录
tar -xf web8.tar -C /var/www/ourdaily
cd /var/www/ourdaily
```

### 2.3 设置Python环境

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install aiohttp aiohttp_jinja2
```

### 2.4 配置Nginx

创建Nginx配置文件：

```bash
sudo nano /etc/nginx/sites-available/ourdaily
```

添加以下内容：

```nginx
server {
    listen 80;
    server_name your_domain_or_ip;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /var/www/ourdaily/src/static;
        expires 30d;
    }

    location /downloads {
        alias /var/www/ourdaily/src/static/downloads;
        expires 30d;
    }
}
```

启用配置并重启Nginx：

```bash
sudo ln -sf /etc/nginx/sites-available/ourdaily /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 2.5 启动应用

```bash
# 确保在虚拟环境中
cd /var/www/ourdaily
source venv/bin/activate

# 启动云端服务
python cloud/cloud_model_server.py --host 0.0.0.0 --port 5000 --llama-host localhost --llama-port 8089
```

为了让应用在后台运行，可以使用systemd创建服务：

```bash
sudo nano /etc/systemd/system/ourdaily.service
```

添加以下内容：

```ini
[Unit]
Description=OurDaily.ai Web Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/ourdaily
ExecStart=/var/www/ourdaily/venv/bin/python cloud/cloud_model_server.py --host 0.0.0.0 --port 5000 --llama-host localhost --llama-port 8089
Restart=always

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable ourdaily
sudo systemctl start ourdaily
```

## 3. 端云协同功能配置

### 3.1 配置云端API

编辑云端API配置文件：

```bash
nano /var/www/ourdaily/cloud/config.json
```

根据您的环境修改以下内容：

```json
{
  "api_keys": ["your-secure-api-key"],
  "allowed_origins": ["https://your-domain.com"],
  "log_level": "info",
  "max_request_size": "10mb"
}
```

### 3.2 配置安装包下载

确保安装包文件位于正确位置：

```bash
# 创建下载目录（如果不存在）
mkdir -p /var/www/ourdaily/src/static/downloads

# 将Windows和macOS安装包放入下载目录
cp OurDaily-Windows-Setup.exe /var/www/ourdaily/src/static/downloads/
cp OurDaily-macOS.dmg /var/www/ourdaily/src/static/downloads/

# 设置正确的权限
sudo chown -R www-data:www-data /var/www/ourdaily/src/static/downloads
sudo chmod -R 755 /var/www/ourdaily/src/static/downloads
```

## 4. 验证部署

### 4.1 检查服务状态

```bash
sudo systemctl status ourdaily
```

### 4.2 检查网站访问

在浏览器中访问您的域名或IP地址，确认网站正常加载。

### 4.3 测试功能

- 测试语言切换功能
- 测试登录和注册功能
- 测试安装包下载功能
- 测试一键部署功能

## 5. 故障排除

### 5.1 服务无法启动

检查日志：

```bash
sudo journalctl -u ourdaily -n 100
```

常见问题：
- Python依赖缺失：确保所有依赖已安装
- 端口冲突：检查5000端口是否被占用
- 权限问题：确保应用目录权限正确

### 5.2 网站无法访问

检查Nginx配置和状态：

```bash
sudo nginx -t
sudo systemctl status nginx
```

检查防火墙设置：

```bash
sudo ufw status
```

### 5.3 下载功能不工作

检查下载目录权限和文件存在：

```bash
ls -la /var/www/ourdaily/src/static/downloads
```

## 6. 更新说明

本版本（web8.tar）包含以下更新：

1. 新增端云协同功能，支持本地处理与云端精修的混合模式
2. 新增一键部署功能，简化用户本地环境配置
3. 首页新增Windows/Mac安装程序下载入口
4. 优化多语言支持，确保所有功能在不同语言环境下正常工作
5. 修复了Jinja2模板渲染兼容性问题

## 7. 联系支持

如果您在部署过程中遇到任何问题，请联系我们的技术支持团队：

- 邮箱：support@ourdaily.ai
- 技术支持热线：+1-800-OURDAILY
