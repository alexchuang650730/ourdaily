# 云侧部署与配置指南

本文档提供了云侧大模型服务器的部署和配置指南，帮助您快速搭建符合接口规范的文本生成服务。

## 系统要求

- Python 3.8+
- aiohttp 3.8+
- 至少8GB内存（推荐16GB以上）
- 支持CUDA的GPU（用于生产环境）

## 快速部署

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install aiohttp pydantic
```

### 2. 配置服务器

服务器配置可通过环境变量或配置文件进行设置：

```bash
# 设置环境变量
export MODEL_HOST="0.0.0.0"  # 监听所有网络接口
export MODEL_PORT="8088"     # 服务端口，与接口文档一致
export MODEL_TIMEOUT="30"    # 默认请求超时时间（秒）
```

### 3. 启动服务器

```bash
# 直接启动
python cloud_model_server.py

# 或使用生产环境工具如Supervisor
supervisord -c supervisor.conf
```

## Docker部署（推荐）

### 1. 准备Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cloud_model_server.py .

EXPOSE 8088

CMD ["python", "cloud_model_server.py"]
```

### 2. 构建和运行容器

```bash
# 构建镜像
docker build -t cloud-model-server .

# 运行容器
docker run -d -p 8088:8088 --name model-server cloud-model-server
```

## 流式响应配置

服务器默认支持SSE（Server-Sent Events）格式的流式响应。确保您的Web服务器配置正确支持长连接：

### Nginx配置示例

```nginx
location /completion {
    proxy_pass http://localhost:8088;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
}
```

## 性能优化

1. **批处理请求**：在高负载情况下，考虑实现请求批处理机制
2. **模型量化**：使用量化技术减少模型内存占用
3. **负载均衡**：部署多个服务实例，使用负载均衡分发请求

## 监控与日志

服务器默认将日志输出到标准输出。在生产环境中，建议配置结构化日志并集成监控系统：

```bash
# 设置日志级别
export LOG_LEVEL="INFO"  # 可选：DEBUG, INFO, WARNING, ERROR

# 设置日志文件
export LOG_FILE="/var/log/model-server.log"
```

## 故障排除

### 常见问题

1. **服务无法启动**
   - 检查端口是否被占用：`netstat -tuln | grep 8088`
   - 确认Python版本兼容性

2. **请求超时**
   - 增加超时设置：修改`MODEL_TIMEOUT`环境变量
   - 检查模型加载是否正常

3. **流式响应不工作**
   - 确认客户端支持SSE
   - 检查代理服务器配置是否支持长连接

## 安全建议

1. 在生产环境中添加适当的认证机制
2. 使用HTTPS加密传输
3. 实施请求速率限制
4. 定期更新依赖包
