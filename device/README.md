# 端云协同设备端组件

本目录包含OurDaily.ai平台的设备端组件，实现与云端服务的协同工作能力。

## 目录结构

- `local_server/`: 本地服务器实现，包含vLLM服务、Owl Agent集成和云端通信
- `owl_integration_guide.md`: Owl Agent集成详细指南
- `owl_integration_summary.md`: Owl集成摘要和关键点

## 主要功能

1. **本地大模型服务**：通过vLLM提供本地推理能力
2. **端云协同**：与云端服务器协作，实现本地处理与云端精修的混合模式
3. **一键部署**：提供Windows和macOS的一键安装部署能力
4. **自动化配置**：自动检测和配置系统环境，包括Docker Desktop安装

## 使用方法

请参考`owl_integration_guide.md`获取详细的安装和配置指南。

## 开发说明

设备端组件与云端API紧密协作，请确保遵循`../cloud/cloud_api_specification.md`中定义的接口规范。
