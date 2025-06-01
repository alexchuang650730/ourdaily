# 云侧大模型API接口规范

本文档详细说明了云侧大模型（Qwen-A2-35B-A22B）的API接口规范，用于端侧与云侧的通信。

## 基本信息

- **接口地址**：`http://34.87.121.105:8088/completion`
- **请求方法**：`POST`
- **请求格式**：`application/json`

## 请求参数

| 字段 | 类型 | 是否必填 | 说明 |
|------|------|----------|------|
| prompt | string | 是 | 提示词文本 |
| n_predict | int | 否 | 生成最大token数量（如256） |
| temperature | float | 否 | 控制输出多样性（0-1） |
| top_k | int | 否 | Top-k采样限制 |
| top_p | float | 否 | Top-p概率限制（nucleus sampling） |
| stream | boolean | 否 | 是否启用流式返回（建议支持SSE） |

### 请求示例

```json
{
  "prompt": "用一句话介绍大语言模型。",
  "n_predict": 256,
  "temperature": 0.7,
  "top_k": 40,
  "top_p": 0.9,
  "stream": true
}
```

## 响应格式

### 非流式（stream: false）

```json
{
  "completion": "大语言模型是一种使用海量数据训练的人工智能模型，能够理解和生成自然语言文本。"
}
```

### 流式（stream: true）

使用Server-Sent Events (SSE)格式返回：

```
data: {"content":"大"}
data: {"content":"语言"}
data: {"content":"模型"}
...
```

## 错误码说明

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 408 | 请求超时 |
| 500 | 服务端内部错误 |

### 错误响应示例

```json
{
  "error": "缺少必需参数: prompt"
}
```

## 注意事项

1. 所有请求参数应进行有效性验证
2. 流式响应推荐使用SSE格式
3. 请求超时时间应根据生成token数量动态调整
4. 服务器应妥善处理并记录所有异常情况
