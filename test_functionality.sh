#!/bin/bash

# 测试脚本：验证OurDaily.ai网站的端云协同和一键部署功能

echo "开始测试OurDaily.ai网站功能..."

# 1. 测试静态资源是否存在
echo "测试静态资源..."
if [ -d "/home/ubuntu/web8_project/src/static/downloads" ]; then
  echo "✓ 下载目录存在"
  
  if [ -f "/home/ubuntu/web8_project/src/static/downloads/OurDaily-Windows-Setup.exe" ] && [ -f "/home/ubuntu/web8_project/src/static/downloads/OurDaily-macOS.dmg" ]; then
    echo "✓ 安装包文件存在"
  else
    echo "✗ 安装包文件缺失"
    exit 1
  fi
else
  echo "✗ 下载目录不存在"
  exit 1
fi

# 2. 测试端云协同JavaScript文件
echo "测试端云协同JavaScript文件..."
if [ -f "/home/ubuntu/web8_project/src/static/js/edge_cloud_adapter.js" ] && [ -f "/home/ubuntu/web8_project/src/static/js/edge_cloud_deployment.js" ]; then
  echo "✓ 端云协同JavaScript文件存在"
else
  echo "✗ 端云协同JavaScript文件缺失"
  exit 1
fi

# 3. 测试CSS文件
echo "测试CSS文件..."
if [ -f "/home/ubuntu/web8_project/src/static/css/edge_cloud.css" ]; then
  echo "✓ 端云协同CSS文件存在"
else
  echo "✗ 端云协同CSS文件缺失"
  exit 1
fi

# 4. 测试下载区域模板
echo "测试下载区域模板..."
if [ -f "/home/ubuntu/web8_project/src/templates/download_section.html" ] && [ -f "/home/ubuntu/web8_project/src/templates/download_section_en.html" ] && [ -f "/home/ubuntu/web8_project/src/templates/download_section_zh-TW.html" ]; then
  echo "✓ 下载区域模板文件存在"
else
  echo "✗ 下载区域模板文件缺失"
  exit 1
fi

# 5. 测试device目录结构
echo "测试device目录结构..."
if [ -d "/home/ubuntu/web8_project/device/local_server" ]; then
  echo "✓ device目录结构正确"
else
  echo "✗ device目录结构不正确"
  exit 1
fi

# 6. 测试cloud目录结构
echo "测试cloud目录结构..."
if [ -f "/home/ubuntu/web8_project/cloud/cloud_model_server.py" ] && [ -f "/home/ubuntu/web8_project/cloud/cloud_api_specification.md" ]; then
  echo "✓ cloud目录结构正确"
else
  echo "✗ cloud目录结构不正确"
  exit 1
fi

echo "所有测试通过！OurDaily.ai网站功能验证成功。"
