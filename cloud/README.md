# Cloud 目录 - 云侧大模型服务

本目录包含与云侧大模型服务相关的所有代码和文档，基于最新的接口规范实现。

## 目录结构

- `cloud_model_server.py` - 云侧大模型服务器实现，支持流式和非流式文本生成
- `cloud_api_specification.md` - 云侧API接口规范文档
- `cloud_deployment_guide.md` - 云侧部署与配置指南
- `README.md` - 本说明文件

## 接口说明

- **接口地址**：`http://34.87.121.105:8088/completion`
- **请求方法**：`POST`
- **请求格式**：`application/json`

## 快速开始

1. 安装依赖：
   ```bash
   pip install aiohttp pydantic
   ```

2. 启动服务器：
   ```bash
   python cloud_model_server.py
   ```

3. 测试接口（非流式）：
   ```bash
   curl -X POST http://localhost:8088/completion \
     -H "Content-Type: application/json" \
     -d '{"prompt": "用一句话介绍大语言模型。", "stream": false}'
   ```

4. 测试接口（流式）：
   ```bash
   curl -X POST http://localhost:8089/completion \
     -H "Content-Type: application/json" \
     -d '{"prompt": "用一句话介绍大语言模型。", "stream": true}'
   ```

## 主要功能

- 完整实现接口文档规范的文本生成API
- 支持流式（SSE格式）和非流式响应
- 完整的参数验证和错误处理
- 可配置的超时和性能参数

## 部署说明

详细的部署和配置说明请参考 `cloud_deployment_guide.md`。

## API文档

完整的API规范请参考 `cloud_api_specification.md`。
