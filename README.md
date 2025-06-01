# OurDaily.ai - 个人与团队的日常自动化助手

OurDaily.ai是一个功能强大的日常自动化平台，旨在简化个人和团队的工作流程，提高生产力，让用户专注于真正重要的事情。

## 主要功能

### 多语言支持
- 完整支持简体中文、繁体中文和英文界面
- 智能语言检测与切换
- 所有功能在不同语言环境下保持一致体验

### 智能下载
- 自动检测用户操作系统，提供对应的安装包
- 支持Windows和macOS平台
- 一键下载与安装

### AI助手
- 多种专业AI助手，满足不同场景需求
- 智能对话与任务处理
- 个性化定制与学习能力

### 用户账户管理
- 安全的注册与登录系统
- 个人资料管理
- 权限控制与安全保障

### 端云协同功能
- 本地处理与云端精修的混合模式
- 离线功能支持
- 数据同步与备份

### 一键部署
- 简化用户本地环境配置
- 自动化安装与设置
- 跨平台兼容性

## 项目结构

```
ourdaily/
├── cloud/                 # 云端服务相关代码
├── device/                # 设备端相关代码
├── instance/              # 应用实例配置
├── src/                   # 主要源代码
│   ├── models/            # 数据模型
│   ├── routes/            # 路由控制
│   ├── static/            # 静态资源(CSS, JS, 图片等)
│   ├── templates/         # HTML模板
│   └── main.py            # 应用入口
├── test_env/              # 测试环境
├── venv/                  # Python虚拟环境
├── deployment_guide.md    # 部署指南
├── requirements.txt       # Python依赖列表
└── test_functionality.sh  # 功能测试脚本
```

## 技术栈

- **后端**: Python, Flask, SQLAlchemy
- **前端**: HTML5, CSS3, JavaScript, Bootstrap
- **数据库**: SQLite (开发), PostgreSQL (生产)
- **部署**: Nginx, Gunicorn
- **AI模型**: 自研模型与第三方API集成

## 部署指南

### 系统要求

#### 服务器端
- 操作系统：Ubuntu 20.04 LTS或更高版本
- Python 3.8+
- Node.js 14+
- Nginx
- 至少2GB RAM和10GB存储空间

#### 客户端（用户设备）
- Windows 10/11 64位或macOS 11.0+
- 至少4GB RAM
- 支持现代浏览器（Chrome, Firefox, Safari, Edge）

### 快速部署

1. **准备环境**
```bash
# 更新系统
sudo apt update && sudo apt upgrade -y
# 安装依赖
sudo apt install -y python3-pip python3-venv nginx
# 创建应用目录
mkdir -p /var/www/ourdaily
```

2. **解压文件**
```bash
# 解压到应用目录
tar -xf web8.tar -C /var/www/ourdaily
cd /var/www/ourdaily
```

3. **设置Python环境**
```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
# 安装依赖
pip install -r requirements.txt
```

4. **配置Nginx**
```bash
# 创建配置文件
sudo nano /etc/nginx/sites-available/ourdaily
# 启用配置
sudo ln -sf /etc/nginx/sites-available/ourdaily /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

5. **启动应用**
```bash
# 确保在虚拟环境中
cd /var/www/ourdaily
source venv/bin/activate
# 启动云端服务
python cloud/cloud_model_server.py --host 0.0.0.0 --port 5000
```

详细部署步骤请参考 [deployment_guide.md](deployment_guide.md)

## 特色功能

### 端云协同
OurDaily.ai采用创新的端云协同架构，将本地处理能力与云端服务无缝结合：
- 本地处理常见任务，减少网络依赖
- 云端处理复杂任务，提供高质量结果
- 智能调度，根据任务类型和网络状况自动选择最佳处理方式

### 多语言支持
完整的多语言支持确保全球用户都能获得一致的体验：
- 界面元素完全本地化
- 智能内容翻译
- 语言偏好记忆

### 一键部署
简化的部署流程让用户能够快速开始使用：
- 自动环境检测
- 依赖项自动安装
- 配置向导

## 开发指南

### 环境设置
```bash
# 克隆仓库
git clone https://github.com/alexchuang650730/ourdaily.git
cd ourdaily

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 运行开发服务器
```bash
# 确保在项目根目录
python src/main.py
```

### 测试
```bash
# 运行测试脚本
./test_functionality.sh
```

## 贡献指南
我们欢迎社区贡献，请遵循以下步骤：
1. Fork仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建Pull Request

## 许可证
本项目采用MIT许可证 - 详情请参阅LICENSE文件

## 联系支持
如果您在使用过程中遇到任何问题，请联系我们的技术支持团队：
- 邮箱：support@ourdaily.ai
- 技术支持热线：+1-800-OURDAILY
