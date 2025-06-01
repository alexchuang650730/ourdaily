"""
Owl Agent Service - 集成适配层

此模块提供了与Camel-AI Owl的集成适配层，允许本地服务器通过vLLM与Owl Agent进行交互。
适配层设计为可在实际部署环境中无缝替换模拟实现，并提供标准化的接口。
同时包含Docker Desktop的自动检测与安装引导功能。
"""

import asyncio
import logging
import platform
import subprocess
import os
import sys
import json
from typing import Dict, List, Optional, Tuple, Any, Union

# 导入本地服务器的配置和工具
from local_server.core.config import Settings
from local_server.utils.logging_config import setup_logger

logger = logging.getLogger(__name__)

class DockerDesktopManager:
    """
    Docker Desktop管理器，负责检测、安装和配置Docker Desktop
    """
    
    def __init__(self):
        """初始化Docker Desktop管理器"""
        self.logger = setup_logger("docker_desktop_manager")
        self.system = platform.system()  # 'Windows', 'Darwin' (macOS), 'Linux'
        
    async def is_installed(self) -> bool:
        """
        检查Docker Desktop是否已安装
        
        Returns:
            bool: 是否已安装
        """
        try:
            if self.system == "Windows":
                # 检查Windows上的Docker Desktop安装
                result = subprocess.run(
                    ["powershell", "-Command", 
                     "Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | " +
                     "Select-Object DisplayName | " +
                     "Where-Object {$_.DisplayName -like '*Docker Desktop*'}"],
                    capture_output=True, text=True
                )
                return "Docker Desktop" in result.stdout
            elif self.system == "Darwin":  # macOS
                # 检查macOS上的Docker Desktop安装
                return os.path.exists("/Applications/Docker.app")
            else:
                # Linux通常不使用Docker Desktop，而是直接使用Docker Engine
                result = subprocess.run(["docker", "--version"], 
                                       capture_output=True, text=True)
                return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Error checking Docker installation: {str(e)}")
            return False
    
    async def is_running(self) -> bool:
        """
        检查Docker Desktop是否正在运行
        
        Returns:
            bool: 是否正在运行
        """
        try:
            result = subprocess.run(["docker", "info"], 
                                   capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Error checking Docker status: {str(e)}")
            return False
    
    async def download_installer(self) -> str:
        """
        下载Docker Desktop安装程序
        
        Returns:
            str: 安装程序的本地路径
        """
        self.logger.info("Downloading Docker Desktop installer...")
        
        download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(download_dir, exist_ok=True)
        
        if self.system == "Windows":
            installer_url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            installer_path = os.path.join(download_dir, "DockerDesktopInstaller.exe")
        elif self.system == "Darwin":
            # 检测是否为Apple Silicon
            is_arm = platform.machine() == 'arm64'
            if is_arm:
                installer_url = "https://desktop.docker.com/mac/main/arm64/Docker.dmg"
            else:
                installer_url = "https://desktop.docker.com/mac/main/amd64/Docker.dmg"
            installer_path = os.path.join(download_dir, "Docker.dmg")
        else:
            raise NotImplementedError("Automatic Docker installation not supported on Linux")
        
        # 使用适当的下载工具
        try:
            import requests
            self.logger.info(f"Downloading from {installer_url} to {installer_path}")
            
            response = requests.get(installer_url, stream=True)
            response.raise_for_status()
            
            with open(installer_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            self.logger.info(f"Download completed: {installer_path}")
            return installer_path
            
        except Exception as e:
            self.logger.error(f"Failed to download Docker Desktop: {str(e)}")
            raise
    
    async def install(self, installer_path: str) -> bool:
        """
        安装Docker Desktop
        
        Args:
            installer_path: 安装程序的本地路径
            
        Returns:
            bool: 安装是否成功
        """
        self.logger.info(f"Installing Docker Desktop from {installer_path}...")
        
        try:
            if self.system == "Windows":
                # 静默安装Docker Desktop
                process = subprocess.Popen(
                    [installer_path, "install", "--quiet"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, stderr = process.communicate()
                
                if process.returncode != 0:
                    self.logger.error(f"Installation failed: {stderr.decode()}")
                    return False
                
                self.logger.info("Docker Desktop installation completed successfully")
                return True
                
            elif self.system == "Darwin":
                # 挂载DMG
                subprocess.run(["hdiutil", "attach", installer_path], check=True)
                
                # 复制到Applications
                subprocess.run(
                    ["cp", "-r", "/Volumes/Docker/Docker.app", "/Applications/"],
                    check=True
                )
                
                # 卸载DMG
                subprocess.run(["hdiutil", "detach", "/Volumes/Docker"], check=True)
                
                self.logger.info("Docker Desktop installation completed successfully")
                return True
                
            else:
                self.logger.error("Automatic Docker installation not supported on Linux")
                return False
                
        except Exception as e:
            self.logger.error(f"Error during Docker Desktop installation: {str(e)}")
            return False
    
    async def configure(self, resources: Dict[str, Any] = None) -> bool:
        """
        配置Docker Desktop资源和设置
        
        Args:
            resources: 资源配置，包含CPU、内存和GPU设置
            
        Returns:
            bool: 配置是否成功
        """
        if resources is None:
            resources = {
                "cpu": 2,
                "memory": 4096,  # MB
                "swap": 1024,    # MB
                "use_gpu": True
            }
            
        self.logger.info(f"Configuring Docker Desktop with resources: {resources}")
        
        try:
            # Docker Desktop配置文件路径
            if self.system == "Windows":
                config_path = os.path.join(os.path.expanduser("~"), 
                                          "AppData", "Roaming", "Docker", "settings.json")
            elif self.system == "Darwin":
                config_path = os.path.join(os.path.expanduser("~"), 
                                          "Library", "Group Containers", 
                                          "group.com.docker", "settings.json")
            else:
                self.logger.warning("Docker Desktop configuration not supported on Linux")
                return False
            
            # 读取现有配置
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
            else:
                config = {}
            
            # 更新资源配置
            if "resources" not in config:
                config["resources"] = {}
                
            config["resources"]["cpus"] = resources["cpu"]
            config["resources"]["memoryMiB"] = resources["memory"]
            config["resources"]["swapMiB"] = resources["swap"]
            
            # 更新GPU配置
            if "wslEngineEnabled" not in config:
                config["wslEngineEnabled"] = True
                
            if resources["use_gpu"]:
                if "wslGpuSupport" not in config:
                    config["wslGpuSupport"] = True
            
            # 保存配置
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
                
            self.logger.info("Docker Desktop configuration updated successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error configuring Docker Desktop: {str(e)}")
            return False
    
    async def ensure_installed_and_running(self) -> bool:
        """
        确保Docker Desktop已安装并正在运行
        如果未安装，则下载并安装
        如果未运行，则启动
        
        Returns:
            bool: Docker Desktop是否可用
        """
        # 检查是否已安装
        if not await self.is_installed():
            self.logger.info("Docker Desktop not installed, attempting to download and install...")
            try:
                installer_path = await self.download_installer()
                if not await self.install(installer_path):
                    self.logger.error("Failed to install Docker Desktop")
                    return False
                
                # 安装后配置资源
                await self.configure()
                
                self.logger.info("Docker Desktop installed successfully, please restart your computer")
                return False  # 需要重启计算机
                
            except Exception as e:
                self.logger.error(f"Error during Docker Desktop installation: {str(e)}")
                return False
        
        # 检查是否正在运行
        if not await self.is_running():
            self.logger.info("Docker Desktop is installed but not running, attempting to start...")
            
            try:
                if self.system == "Windows":
                    subprocess.Popen(
                        ["powershell", "-Command", "Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                elif self.system == "Darwin":
                    subprocess.Popen(
                        ["open", "-a", "Docker"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                
                # 等待Docker启动
                for _ in range(30):  # 最多等待30秒
                    await asyncio.sleep(1)
                    if await self.is_running():
                        self.logger.info("Docker Desktop started successfully")
                        return True
                
                self.logger.error("Timed out waiting for Docker Desktop to start")
                return False
                
            except Exception as e:
                self.logger.error(f"Error starting Docker Desktop: {str(e)}")
                return False
        
        return True  # Docker已安装且正在运行

class OwlAgentService:
    """
    Owl Agent服务适配器，提供与Camel-AI Owl的集成接口。
    
    此类负责:
    1. 初始化和配置Owl Agent
    2. 将任务提交给Owl Agent处理
    3. 处理Owl Agent的响应
    4. 管理与vLLM的集成
    5. 检测和管理Docker Desktop
    """
    
    def __init__(self, config: Settings):
        """
        初始化Owl Agent服务适配器
        
        Args:
            config: 应用程序配置，包含Owl和vLLM相关设置
        """
        self.config = config
        self.logger = setup_logger("owl_agent_service")
        self._owl_agent_instance = None
        self.vllm_endpoint = config.vllm_service_url
        self.model_name = config.local_model_name
        self.docker_manager = DockerDesktopManager()
        
        # 在实际部署时，这些将被替换为真实的Owl导入
        # from camel.agents import ChatAgent
        # from camel.societies import RolePlaying
        # from owl.utils.enhanced_role_playing import OwlRolePlaying, run_society
        
        self.logger.info(f"OwlAgentService initialized with model: {self.model_name}")
        self.logger.info(f"vLLM endpoint: {self.vllm_endpoint}")
    
    async def ensure_docker_ready(self) -> bool:
        """
        确保Docker Desktop已安装并正在运行
        
        Returns:
            bool: Docker是否准备就绪
        """
        return await self.docker_manager.ensure_installed_and_running()
    
    async def initialize(self) -> bool:
        """
        异步初始化Owl Agent，建立与vLLM的连接
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            # 首先确保Docker Desktop已准备就绪
            docker_ready = await self.ensure_docker_ready()
            if not docker_ready:
                self.logger.error("Docker Desktop is not ready, cannot initialize Owl Agent")
                return False
            
            self.logger.info("Initializing Owl Agent...")
            
            # 在实际部署时，这里将初始化真实的Owl Agent
            # 示例代码（将在实际部署时替换）:
            # from owl.utils.enhanced_role_playing import OwlRolePlaying
            # self._owl_agent_instance = OwlRolePlaying(
            #     model=self.model_name,
            #     assistant_role_name="AI Assistant",
            #     user_role_name="User",
            #     assistant_agent_kwargs={
            #         "model": self.model_name,
            #         "base_url": self.vllm_endpoint,
            #     },
            #     user_agent_kwargs={
            #         "model": self.model_name,
            #         "base_url": self.vllm_endpoint,
            #     }
            # )
            
            # 模拟初始化成功
            self._owl_agent_instance = "SimulatedOwlAgentInstance"
            self.logger.info("Owl Agent initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Owl Agent: {str(e)}")
            return False
    
    async def process_task(self, 
                          task_description: str, 
                          context: Optional[str] = None,
                          max_turns: int = 10) -> Dict[str, Any]:
        """
        处理任务并返回Owl Agent的响应
        
        Args:
            task_description: 任务描述
            context: 可选的上下文信息
            max_turns: 最大对话轮次
            
        Returns:
            Dict包含:
                - answer: Owl Agent的回答
                - chat_history: 对话历史
                - token_info: Token使用信息
                - success: 处理是否成功
                - error: 如果失败，包含错误信息
        """
        if not self._owl_agent_instance:
            await self.initialize()
            
        try:
            self.logger.info(f"Processing task: {task_description[:100]}...")
            
            # 在实际部署时，这里将调用真实的Owl Agent API
            # 示例代码（将在实际部署时替换）:
            # from owl.utils.enhanced_role_playing import run_society
            # society = self._owl_agent_instance
            # society.task_prompt = task_description
            # if context:
            #     society.context = context
            # society.max_turns = max_turns
            # answer, chat_history, token_info = run_society(society)
            
            # 模拟处理结果
            await asyncio.sleep(1)  # 模拟处理时间
            simulated_outcome = {
                "answer": f"这是对任务的模拟回答: {task_description[:50]}...",
                "chat_history": [
                    {"role": "user", "content": task_description},
                    {"role": "assistant", "content": f"这是对任务的模拟回答: {task_description[:50]}..."}
                ],
                "token_info": {
                    "prompt_tokens": 150,
                    "completion_tokens": 200,
                    "total_tokens": 350
                },
                "success": True,
                "error": None
            }
            
            self.logger.info(f"Task processed successfully, tokens used: {simulated_outcome['token_info']['total_tokens']}")
            return simulated_outcome
            
        except Exception as e:
            error_msg = f"Error processing task: {str(e)}"
            self.logger.error(error_msg)
            return {
                "answer": None,
                "chat_history": None,
                "token_info": None,
                "success": False,
                "error": error_msg
            }
    
    async def health_check(self) -> bool:
        """
        检查Owl Agent和vLLM服务的健康状态
        
        Returns:
            bool: 服务是否健康
        """
        try:
            # 首先检查Docker状态
            docker_running = await self.docker_manager.is_running()
            if not docker_running:
                self.logger.error("Docker Desktop is not running")
                return False
            
            # 在实际部署时，这里将检查真实的Owl Agent和vLLM服务
            # 示例代码（将在实际部署时替换）:
            # import httpx
            # async with httpx.AsyncClient() as client:
            #     response = await client.get(f"{self.vllm_endpoint}/health")
            #     if response.status_code != 200:
            #         return False
            
            # 模拟健康检查
            return self._owl_agent_instance is not None
            
        except Exception as e:
            self.logger.error(f"Health check failed: {str(e)}")
            return False
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        获取当前使用的模型信息
        
        Returns:
            Dict: 包含模型名称、端点等信息
        """
        return {
            "model_name": self.model_name,
            "vllm_endpoint": self.vllm_endpoint,
            "initialized": self._owl_agent_instance is not None,
            "docker_status": {
                "installed": asyncio.run(self.docker_manager.is_installed()),
                "running": asyncio.run(self.docker_manager.is_running())
            }
        }
