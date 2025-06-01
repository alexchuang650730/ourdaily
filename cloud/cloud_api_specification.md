# 云侧大模型API接口说明

本文档详细说明了云侧大模型（Qwen-A2-35B-A22B）的API接口规范，用于端侧与云侧的通信。

## 1. API概述

云侧大模型采用标准的RESTful API接口，主要包含以下端点：

### 1.1 基础URL

```
https://{cloud_server_host}:{cloud_server_port}/api/v1
```

### 1.2 认证方式

所有API请求需要包含认证头：

```
Authorization: Bearer {API_KEY}
```

## 2. 接口详情

### 2.1 精修接口

用于接收端侧请求并返回云端精修结果。

**请求方式**：POST  
**URL**：`/api/v1/refinement`

**请求参数**：
```json
{
  "request_id": "unique-request-id-123",
  "prompt": "原始用户提问内容",
  "local_response": "端侧模型生成的回答",
  "confidence_details": {
    "rouge_score": 0.75,
    "rouge_threshold": 0.8,
    "keyword_triggers": ["emergency", "critical"]
  },
  "model_params": {
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 2048
  }
}
```

**响应格式**：
```json
{
  "request_id": "unique-request-id-123",
  "refined_response": "云端精修后的回答内容",
  "token_usage": {
    "prompt_tokens": 320,
    "completion_tokens": 450,
    "total_tokens": 770
  },
  "processing_time": 1.25,
  "model_used": "Qwen-A2-35B-A22B"
}
```

### 2.2 健康检查接口

用于检查云侧服务状态。

**请求方式**：GET  
**URL**：`/api/v1/health`

**响应格式**：
```json
{
  "status": "healthy",
  "model_status": "loaded",
  "current_load": 0.35,
  "available_models": ["Qwen-A2-35B-A22B"],
  "version": "1.2.0"
}
```

### 2.3 批量处理接口

用于批量处理多个精修请求。

**请求方式**：POST  
**URL**：`/api/v1/batch_refinement`

**请求参数**：
```json
{
  "batch_id": "batch-123",
  "requests": [
    {
      "request_id": "req-1",
      "prompt": "...",
      "local_response": "...",
      "confidence_details": {...}
    },
    {
      "request_id": "req-2",
      "prompt": "...",
      "local_response": "...",
      "confidence_details": {...}
    }
  ],
  "model_params": {...}
}
```

**响应格式**：
```json
{
  "batch_id": "batch-123",
  "results": [
    {
      "request_id": "req-1",
      "refined_response": "...",
      "token_usage": {...}
    },
    {
      "request_id": "req-2",
      "refined_response": "...",
      "token_usage": {...}
    }
  ],
  "total_processing_time": 2.5,
  "total_token_usage": {
    "prompt_tokens": 650,
    "completion_tokens": 820,
    "total_tokens": 1470
  }
}
```

## 3. 错误处理

标准HTTP状态码用于表示请求状态，错误响应格式为：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "详细错误信息",
    "request_id": "unique-request-id-123"
  }
}
```

常见错误代码：

| 错误代码 | 描述 |
|---------|------|
| invalid_request | 请求参数无效 |
| unauthorized | 认证失败 |
| rate_limit_exceeded | 超出请求速率限制 |
| model_overloaded | 模型负载过高 |
| internal_error | 内部服务器错误 |

## 4. 限制与注意事项

- 请求速率限制：每分钟60个请求
- 最大请求大小：10MB
- 最大响应时间：30秒
- 批量请求最大数量：20个子请求

## 5. 部署配置

云侧服务器默认配置：

- 监听地址：0.0.0.0
- 默认端口：8765
- TLS/SSL：必须启用（生产环境）
- 日志级别：INFO

## 6. 安全建议

- 定期轮换API密钥
- 使用IP白名单限制访问
- 启用请求日志审计
- 监控异常请求模式
