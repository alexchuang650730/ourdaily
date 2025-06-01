"""
云侧大模型服务器 - 基于新接口规范实现，集成Jinja2模板渲染

此模块实现了云侧大模型服务器，提供文本生成API接口和仪表板数据接口。
- 大模型API接口: http://34.87.121.105:8089/completion
- 仪表板数据接口: http://34.87.121.105:5000/api/*
"""

import asyncio
import json
import logging
import ssl
import uuid
import time
import os
import datetime
from datetime import datetime
from typing import Dict, Any, Optional, List, AsyncGenerator
from aiohttp import web, ClientSession, ClientTimeout
import argparse
import jinja2
import aiohttp_jinja2

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("cloud_model_server")

# 默认配置
DEFAULT_HOST = "0.0.0.0"  # 监听所有网络接口
DEFAULT_PORT = 5000       # 仪表板数据接口端口
DEFAULT_LLAMA_HOST = "localhost"  # 默认llamaserver主机
DEFAULT_LLAMA_PORT = 8089  # 默认llamaserver端口
COMPLETION_PATH = "/completion"  # 大模型接口路径
WORK_LIST_PATH = "/api/works"  # 工作列表接口
OPERATION_HISTORY_PATH = "/api/operations"  # 操作历史接口
RECORDINGS_PATH = "/api/recordings"  # 录屏接口
CREATE_WORK_PATH = "/api/works/create"  # 创建工作接口
SEND_PROMPT_PATH = "/api/completion"  # 发送指令接口
UPLOAD_RECORDING_PATH = "/api/recordings/upload"  # 上传录屏接口

# 数据存储目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
WORKS_FILE = os.path.join(DATA_DIR, "works.json")
OPERATIONS_FILE = os.path.join(DATA_DIR, "operations.json")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# 云侧大模型服务
class CloudModelService:
    def __init__(self, llama_host: str, llama_port: int):
        self.model_name = "Qwen-A2-35B-A22B"
        self.version = "1.0.0"
        self.llama_url = f"http://{llama_host}:{llama_port}/completion"
        self.works = self._load_works()
        self.operations = self._load_operations()
        logger.info(f"初始化CloudModelService，连接到llamaserver: {self.llama_url}")
        logger.info(f"已加载 {len(self.works)} 个工作和 {len(self.operations)} 条操作记录")
    
    def _load_works(self) -> List[Dict[str, Any]]:
        """加载工作列表"""
        if os.path.exists(WORKS_FILE):
            try:
                with open(WORKS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载工作列表失败: {str(e)}")
        return []
    
    def _save_works(self):
        """保存工作列表"""
        try:
            with open(WORKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.works, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存工作列表失败: {str(e)}")
    
    def _load_operations(self) -> List[Dict[str, Any]]:
        """加载操作历史"""
        if os.path.exists(OPERATIONS_FILE):
            try:
                with open(OPERATIONS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载操作历史失败: {str(e)}")
        return []
    
    def _save_operations(self):
        """保存操作历史"""
        try:
            with open(OPERATIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.operations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存操作历史失败: {str(e)}")
    
    def get_works(self) -> List[Dict[str, Any]]:
        """获取工作列表"""
        return self.works
    
    def get_operations(self, work_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取操作历史，可按工作ID筛选"""
        if work_id:
            return [op for op in self.operations if op.get('work_id') == work_id]
        return self.operations
    
    def get_recordings(self, work_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取录屏列表，可按工作ID筛选"""
        recordings = []
        for filename in os.listdir(RECORDINGS_DIR):
            if filename.endswith('.webm') or filename.endswith('.mp4'):
                file_path = os.path.join(RECORDINGS_DIR, filename)
                file_info = os.stat(file_path)
                # 从文件名解析工作ID
                parts = filename.split('_')
                file_work_id = parts[0] if len(parts) > 1 else None
                
                if work_id and file_work_id != work_id:
                    continue
                    
                recordings.append({
                    'id': filename,
                    'work_id': file_work_id,
                    'path': f"/recordings/{filename}",
                    'size': file_info.st_size,
                    'created_at': datetime.fromtimestamp(file_info.st_ctime).isoformat()
                })
        
        # 按创建时间排序
        recordings.sort(key=lambda x: x['created_at'])
        return recordings
    
    def create_work(self, first_prompt: str) -> Dict[str, Any]:
        """创建新工作"""
        work_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        # 截取前30个字符作为标题
        title = first_prompt[:30] + "..." if len(first_prompt) > 30 else first_prompt
        
        work = {
            "id": work_id,
            "title": title,
            "first_prompt": first_prompt,
            "created_at": timestamp,
            "updated_at": timestamp
        }
        
        self.works.append(work)
        self._save_works()
        
        return work
    
    def record_operation(self, work_id: str, prompt: str, completion: str) -> Dict[str, Any]:
        """记录操作历史"""
        operation_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        operation = {
            "id": operation_id,
            "work_id": work_id,
            "prompt": prompt,
            "completion": completion,
            "created_at": timestamp
        }
        
        self.operations.append(operation)
        self._save_operations()
        
        # 更新工作的最后更新时间
        for work in self.works:
            if work["id"] == work_id:
                work["updated_at"] = timestamp
                break
        self._save_works()
        
        return operation
    
    def save_recording(self, work_id: str, file_data: bytes, filename: str) -> Dict[str, Any]:
        """保存录屏文件"""
        # 确保文件名包含工作ID
        if not filename.startswith(f"{work_id}_"):
            filename = f"{work_id}_{filename}"
        
        file_path = os.path.join(RECORDINGS_DIR, filename)
        
        # 写入文件
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        # 获取文件信息
        file_info = os.stat(file_path)
        
        recording = {
            'id': filename,
            'work_id': work_id,
            'path': f"/recordings/{filename}",
            'size': file_info.st_size,
            'created_at': datetime.now().isoformat()
        }
        
        return recording
    
    async def generate_text(self, prompt: str, n_predict: int = 256, 
                           temperature: float = 0.7, top_k: int = 40, 
                           top_p: float = 0.9, stream: bool = False,
                           work_id: Optional[str] = None) -> AsyncGenerator[str, None] | str:
        """
        生成文本响应，通过调用llamaserver API
        
        Args:
            prompt: 提示词
            n_predict: 生成最大token数量
            temperature: 控制输出多样性 (0-1)
            top_k: Top-k采样限制
            top_p: Top-p概率限制
            stream: 是否启用流式返回
            work_id: 工作ID，如果为None则创建新工作
            
        Returns:
            如果stream=True，返回异步生成器；否则返回完整响应字符串
        """
        # 如果没有提供工作ID，创建新工作
        if not work_id:
            work = self.create_work(prompt)
            work_id = work["id"]
        
        # 准备发送到llamaserver的请求数据
        llama_request = {
            "prompt": prompt,
            "n_predict": n_predict,
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "stream": stream
        }
        
        # 设置超时
        timeout = ClientTimeout(total=60)
        
        # 根据stream参数决定返回方式
        if stream:
            # 流式返回
            async def response_generator():
                full_response = ""
                try:
                    async with ClientSession(timeout=timeout) as session:
                        async with session.post(self.llama_url, json=llama_request) as response:
                            if response.status != 200:
                                error_text = await response.text()
                                logger.error(f"llamaserver返回错误: {response.status}, {error_text}")
                                yield f"Error: llamaserver返回状态码 {response.status}"
                                return
                            
                            # 处理llamaserver的流式响应
                            async for line in response.content:
                                line = line.decode('utf-8').strip()
                                if line.startswith('data: '):
                                    try:
                                        data = json.loads(line[6:])
                                        if 'content' in data:
                                            content = data['content']
                                            full_response += content
                                            yield content
                                    except json.JSONDecodeError:
                                        logger.warning(f"无法解析llamaserver响应: {line}")
                    
                    # 记录操作历史
                    self.record_operation(work_id, prompt, full_response)
                    
                except Exception as e:
                    logger.exception(f"流式生成时发生错误: {str(e)}")
                    yield f"Error: {str(e)}"
            
            return response_generator()
        else:
            # 非流式返回
            try:
                async with ClientSession(timeout=timeout) as session:
                    async with session.post(self.llama_url, json=llama_request) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"llamaserver返回错误: {response.status}, {error_text}")
                            return f"Error: llamaserver返回状态码 {response.status}"
                        
                        result = await response.json()
                        completion = result.get('completion', '')
                        
                        # 记录操作历史
                        self.record_operation(work_id, prompt, completion)
                        
                        return completion
            except Exception as e:
                logger.exception(f"非流式生成时发生错误: {str(e)}")
                return f"Error: {str(e)}"
    
    def validate_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证并规范化请求参数
        
        Args:
            params: 请求参数字典
            
        Returns:
            规范化后的参数字典
            
        Raises:
            ValueError: 如果必需参数缺失或参数值无效
        """
        # 检查必需参数
        if "prompt" not in params:
            raise ValueError("缺少必需参数: prompt")
        
        # 规范化参数
        normalized = {
            "prompt": params["prompt"]
        }
        
        # 可选参数及其默认值
        optional_params = {
            "n_predict": 256,
            "temperature": 0.7,
            "top_k": 40,
            "top_p": 0.9,
            "stream": False,
            "work_id": None
        }
        
        # 添加可选参数（如果提供）
        for param, default in optional_params.items():
            if param in params:
                # 类型检查和范围验证
                if param == "n_predict":
                    value = int(params[param])
                    if value <= 0:
                        raise ValueError(f"n_predict 必须为正整数，收到: {value}")
                elif param == "temperature":
                    value = float(params[param])
                    if not 0 <= value <= 1:
                        raise ValueError(f"temperature 必须在 0-1 范围内，收到: {value}")
                elif param == "top_k":
                    value = int(params[param])
                    if value <= 0:
                        raise ValueError(f"top_k 必须为正整数，收到: {value}")
                elif param == "top_p":
                    value = float(params[param])
                    if not 0 <= value <= 1:
                        raise ValueError(f"top_p 必须在 0-1 范围内，收到: {value}")
                elif param == "stream":
                    value = bool(params[param])
                else:
                    value = params[param]
                
                normalized[param] = value
            else:
                normalized[param] = default
        
        return normalized

# 处理HTTP请求的Web应用
class ModelServer:
    def __init__(self, host: str, port: int, llama_host: str, llama_port: int):
        self.host = host
        self.port = port
        self.app = web.Application()
        
        # 设置Jinja2模板引擎
        template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'templates')
        logger.info(f"设置Jinja2模板路径: {template_path}")
        
        # 确保模板目录存在
        if not os.path.exists(template_path):
            logger.warning(f"模板目录不存在: {template_path}，尝试创建")
            os.makedirs(template_path, exist_ok=True)
        
        # 初始化Jinja2环境
        aiohttp_jinja2.setup(
            self.app,
            loader=jinja2.FileSystemLoader(template_path)
        )
        
        self.model_service = CloudModelService(llama_host, llama_port)
        self.setup_routes()
        self.setup_cors()
        self.setup_middlewares()
        
        # 添加Jinja2上下文处理器
        aiohttp_jinja2.get_env(self.app).globals.update(
            url_for=self.url_for
        )
    
    def url_for(self, route_name, **kwargs):
        """生成URL，类似Flask的url_for函数"""
        try:
            url = self.app.router[route_name].url_for(**kwargs)
            return url
        except KeyError:
            logger.error(f"找不到路由名称: {route_name}")
            return f"#error-no-route-{route_name}"
        except Exception as e:
            logger.error(f"生成URL时发生错误: {str(e)}")
            return f"#error-{str(e)}"
    
    def setup_cors(self):
        """设置CORS跨域支持"""
        @web.middleware
        async def cors_middleware(request, handler):
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            return response
        
        self.app.middlewares.append(cors_middleware)
    
    def setup_middlewares(self):
        """设置中间件"""
        @web.middleware
        async def error_middleware(request, handler):
            try:
                return await handler(request)
            except web.HTTPException as ex:
                # 处理HTTP异常
                logger.warning(f"HTTP异常: {ex.status}, {ex.reason}")
                return web.json_response({
                    "error": True,
                    "message": f"{ex.status}: {ex.reason}"
                }, status=ex.status)
            except Exception as e:
                # 处理其他异常
                logger.exception(f"处理请求时发生错误: {str(e)}")
                return web.json_response({
                    "error": True,
                    "message": f"服务器内部错误: {str(e)}"
                }, status=500)
        
        self.app.middlewares.append(error_middleware)
        
        @web.middleware
        async def session_middleware(request, handler):
            # 从cookie获取session_id
            session_id = request.cookies.get('session_id')
            
            # 如果没有session_id，创建一个新的
            if not session_id:
                session_id = str(uuid.uuid4())
            
            # 将session_id添加到请求属性中
            request['session_id'] = session_id
            
            # 处理请求
            response = await handler(request)
            
            # 将session_id设置到响应cookie中
            response.set_cookie('session_id', session_id, max_age=86400, httponly=True)
            
            return response
        
        self.app.middlewares.append(session_middleware)
    
    def setup_routes(self):
        """设置API路由"""
        # 添加根路径处理 - 重定向到首页
        self.app.router.add_get('/', self.handle_root, name='root')
        
        # 添加静态文件服务 - 用于提供前端页面
        static_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'static')
        logger.info(f"设置静态文件路径: {static_path}")
        
        # 确保静态文件目录存在
        if not os.path.exists(static_path):
            logger.warning(f"静态文件目录不存在: {static_path}，尝试创建")
            os.makedirs(static_path, exist_ok=True)
            
        self.app.router.add_static('/static', static_path)
        
        # 添加录屏文件服务
        self.app.router.add_static('/recordings', RECORDINGS_DIR)
        
        # 添加首页路由
        self.app.router.add_get('/index', self.handle_index, name='index')
        
        # 添加认证相关路由
        self.app.router.add_get('/auth/login', self.handle_login_get, name='auth.login')
        self.app.router.add_post('/auth/login', self.handle_login_post, name='auth.login_post')
        self.app.router.add_get('/auth/register', self.handle_register_get, name='auth.register')
        self.app.router.add_post('/auth/register', self.handle_register_post, name='auth.register_post')
        self.app.router.add_get('/auth/logout', self.handle_logout, name='auth.logout')
        
        # 添加仪表板路由
        self.app.router.add_get('/dashboard', self.handle_dashboard, name='dashboard')
        
        # 添加付费页面路由
        self.app.router.add_get('/pricing', self.handle_pricing, name='pricing')
        self.app.router.add_get('/payment', self.handle_payment, name='payment')
        self.app.router.add_post('/payment/process', self.handle_payment_process, name='payment.process')
        
        # 添加AI助手入口检查登录状态路由
        self.app.router.add_get('/check-login', self.handle_check_login, name='check_login')
        
        # 仪表板数据接口
        self.app.router.add_get(WORK_LIST_PATH, self.handle_get_works)
        self.app.router.add_post(CREATE_WORK_PATH, self.handle_create_work)
        self.app.router.add_get(OPERATION_HISTORY_PATH, self.handle_get_operations)
        self.app.router.add_get(RECORDINGS_PATH, self.handle_get_recordings)
        self.app.router.add_post(UPLOAD_RECORDING_PATH, self.handle_upload_recording)
        self.app.router.add_post(SEND_PROMPT_PATH, self.handle_send_prompt)
    
    async def handle_root(self, request):
        """处理根路径请求 - 重定向到首页"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        return web.HTTPFound(f'/index?lang={lang}')
    
    async def handle_index(self, request):
        """处理首页请求"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template_name = 'index_en.html'
        elif lang == 'zh-TW':
            template_name = 'index_zh-TW.html'
        else:
            template_name = 'index.html'
        
        # 检查用户是否已登录
        session_id = request.get('session_id', '')
        is_logged_in = request.cookies.get('is_logged_in') == '1'
        
        # 渲染模板
        context = {
            'lang': lang,
            'is_logged_in': is_logged_in,
            'user': None  # 如果已登录，这里应该包含用户信息
        }
        
        return aiohttp_jinja2.render_template(template_name, request, context)
    
    async def handle_login_get(self, request):
        """处理登录页面GET请求"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template_name = 'login_en.html'
        elif lang == 'zh-TW':
            template_name = 'login_zh-TW.html'
        else:
            template_name = 'login.html'
        
        # 渲染模板
        context = {
            'lang': lang,
            'error_message': None
        }
        
        return aiohttp_jinja2.render_template(template_name, request, context)
    
    async def handle_login_post(self, request):
        """处理登录表单提交"""
        # 获取表单数据
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        lang = data.get('lang', 'zh-CN')
        
        # 这里应该进行实际的用户验证
        # 简化示例：用户名和密码都是"admin"
        if username == 'admin' and password == 'admin':
            # 登录成功，重定向到仪表板
            response = web.HTTPFound(f'/dashboard?lang={lang}')
            
            # 设置登录状态cookie
            response.set_cookie('is_logged_in', '1', max_age=86400, httponly=True)
            response.set_cookie('username', username, max_age=86400, httponly=True)
            
            return response
        else:
            # 登录失败，返回错误信息
            # 根据语言选择模板
            if lang == 'en':
                template_name = 'login_en.html'
                error_message = 'Invalid username or password'
            elif lang == 'zh-TW':
                template_name = 'login_zh-TW.html'
                error_message = '用戶名或密碼無效'
            else:
                template_name = 'login.html'
                error_message = '用户名或密码无效'
            
            # 渲染模板
            context = {
                'lang': lang,
                'error_message': error_message,
                'username': username
            }
            
            return aiohttp_jinja2.render_template(template_name, request, context)
    
    async def handle_register_get(self, request):
        """处理注册页面GET请求"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template_name = 'register_en.html'
        elif lang == 'zh-TW':
            template_name = 'register_zh-TW.html'
        else:
            template_name = 'register.html'
        
        # 渲染模板
        context = {
            'lang': lang,
            'error_message': None
        }
        
        return aiohttp_jinja2.render_template(template_name, request, context)
    
    async def handle_register_post(self, request):
        """处理注册表单提交"""
        # 获取表单数据
        data = await request.post()
        username = data.get('username', '')
        email = data.get('email', '')
        password = data.get('password', '')
        confirm_password = data.get('confirm_password', '')
        lang = data.get('lang', 'zh-CN')
        
        # 验证表单数据
        error_message = None
        
        if not username or not email or not password:
            if lang == 'en':
                error_message = 'All fields are required'
            elif lang == 'zh-TW':
                error_message = '所有欄位都是必填的'
            else:
                error_message = '所有字段都是必填的'
        elif password != confirm_password:
            if lang == 'en':
                error_message = 'Passwords do not match'
            elif lang == 'zh-TW':
                error_message = '密碼不匹配'
            else:
                error_message = '密码不匹配'
        
        if error_message:
            # 注册失败，返回错误信息
            # 根据语言选择模板
            if lang == 'en':
                template_name = 'register_en.html'
            elif lang == 'zh-TW':
                template_name = 'register_zh-TW.html'
            else:
                template_name = 'register.html'
            
            # 渲染模板
            context = {
                'lang': lang,
                'error_message': error_message,
                'username': username,
                'email': email
            }
            
            return aiohttp_jinja2.render_template(template_name, request, context)
        else:
            # 注册成功，重定向到登录页面
            # 这里应该保存用户信息到数据库
            
            # 根据语言选择成功消息
            if lang == 'en':
                success_message = 'Registration successful. Please log in.'
            elif lang == 'zh-TW':
                success_message = '註冊成功。請登錄。'
            else:
                success_message = '注册成功。请登录。'
            
            # 重定向到登录页面
            response = web.HTTPFound(f'/auth/login?lang={lang}')
            
            # 设置成功消息cookie
            response.set_cookie('success_message', success_message, max_age=60, httponly=True)
            
            return response
    
    async def handle_logout(self, request):
        """处理登出请求"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        
        # 清除登录状态cookie
        response = web.HTTPFound(f'/index?lang={lang}')
        response.del_cookie('is_logged_in')
        response.del_cookie('username')
        
        return response
    
    async def handle_check_login(self, request):
        """处理AI助手入口登录状态检查"""
        # 获取语言参数和工具类型
        lang = request.query.get('lang', 'zh-CN')
        tool = request.query.get('tool', 'slides')  # 默认为幻灯片助手
        
        # 检查用户是否已登录
        is_logged_in = request.cookies.get('is_logged_in') == '1'
        
        if is_logged_in:
            # 已登录，重定向到仪表板
            # 创建一个新的工作，初始提示词根据工具类型设置
            initial_prompt = ""
            if tool == 'slides':
                if lang == 'en':
                    initial_prompt = "Create a professional presentation about [topic]"
                elif lang == 'zh-TW':
                    initial_prompt = "創建一個關於[主題]的專業演示文稿"
                else:
                    initial_prompt = "创建一个关于[主题]的专业演示文稿"
            elif tool == 'docs':
                if lang == 'en':
                    initial_prompt = "Write a document about [topic]"
                elif lang == 'zh-TW':
                    initial_prompt = "撰寫一份關於[主題]的文檔"
                else:
                    initial_prompt = "撰写一份关于[主题]的文档"
            elif tool == 'data':
                if lang == 'en':
                    initial_prompt = "Analyze the following data: [data]"
                elif lang == 'zh-TW':
                    initial_prompt = "分析以下數據：[數據]"
                else:
                    initial_prompt = "分析以下数据：[数据]"
            elif tool == 'schedule':
                if lang == 'en':
                    initial_prompt = "Create a schedule for [event/project]"
                elif lang == 'zh-TW':
                    initial_prompt = "為[事件/項目]創建日程安排"
                else:
                    initial_prompt = "为[事件/项目]创建日程安排"
            elif tool == 'email':
                if lang == 'en':
                    initial_prompt = "Write an email about [topic]"
                elif lang == 'zh-TW':
                    initial_prompt = "撰寫一封關於[主題]的電子郵件"
                else:
                    initial_prompt = "撰写一封关于[主题]的电子邮件"
            elif tool == 'code':
                if lang == 'en':
                    initial_prompt = "Write code for [task]"
                elif lang == 'zh-TW':
                    initial_prompt = "為[任務]編寫代碼"
                else:
                    initial_prompt = "为[任务]编写代码"
            
            # 创建工作
            work = self.model_service.create_work(initial_prompt)
            
            # 重定向到仪表板，带上工作ID
            return web.HTTPFound(f'/dashboard?lang={lang}&work_id={work["id"]}')
        else:
            # 未登录，重定向到登录页面
            # 添加一个返回URL参数，登录成功后可以返回到原来的工具
            return web.HTTPFound(f'/auth/login?lang={lang}&next=/check-login?tool={tool}&lang={lang}')
    
    async def handle_dashboard(self, request):
        """处理仪表板页面请求"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        
        # 检查用户是否已登录
        is_logged_in = request.cookies.get('is_logged_in') == '1'
        
        if not is_logged_in:
            # 未登录，重定向到登录页面
            return web.HTTPFound(f'/auth/login?lang={lang}')
        
        # 获取用户名
        username = request.cookies.get('username', 'User')
        
        # 获取工作ID
        work_id = request.query.get('work_id')
        
        # 根据语言选择模板
        if lang == 'en':
            template_name = 'dashboard_en.html'
        elif lang == 'zh-TW':
            template_name = 'dashboard_zh-TW.html'
        else:
            template_name = 'dashboard.html'
        
        # 获取工作列表
        works = self.model_service.get_works()
        
        # 获取当前工作的操作历史和录屏
        operations = []
        recordings = []
        current_work = None
        
        if work_id:
            operations = self.model_service.get_operations(work_id)
            recordings = self.model_service.get_recordings(work_id)
            
            # 获取当前工作详情
            for work in works:
                if work['id'] == work_id:
                    current_work = work
                    break
        
        # 渲染模板
        context = {
            'lang': lang,
            'username': username,
            'works': works,
            'operations': operations,
            'recordings': recordings,
            'current_work': current_work,
            'work_id': work_id
        }
        
        return aiohttp_jinja2.render_template(template_name, request, context)
    
    async def handle_pricing(self, request):
        """处理定价页面请求"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        
        # 检查用户是否已登录
        is_logged_in = request.cookies.get('is_logged_in') == '1'
        username = request.cookies.get('username', '')
        
        # 根据语言选择模板
        if lang == 'en':
            template_name = 'pricing_en.html'
        elif lang == 'zh-TW':
            template_name = 'pricing_zh-TW.html'
        else:
            template_name = 'pricing.html'
        
        # 渲染模板
        context = {
            'lang': lang,
            'is_logged_in': is_logged_in,
            'username': username
        }
        
        return aiohttp_jinja2.render_template(template_name, request, context)
    
    async def handle_payment(self, request):
        """处理支付页面请求"""
        # 获取语言参数，默认为zh-CN
        lang = request.query.get('lang', 'zh-CN')
        plan = request.query.get('plan', 'free')  # 获取选择的套餐
        
        # 检查用户是否已登录
        is_logged_in = request.cookies.get('is_logged_in') == '1'
        
        if not is_logged_in:
            # 未登录，重定向到登录页面
            return web.HTTPFound(f'/auth/login?lang={lang}')
        
        # 获取用户名
        username = request.cookies.get('username', 'User')
        
        # 根据语言选择模板
        if lang == 'en':
            template_name = 'payment_en.html'
        elif lang == 'zh-TW':
            template_name = 'payment_zh-TW.html'
        else:
            template_name = 'payment.html'
        
        # 根据套餐设置价格
        price = 0
        if plan == 'pro':
            price = 99
        elif plan == 'enterprise':
            price = 299
        
        # 渲染模板
        context = {
            'lang': lang,
            'username': username,
            'plan': plan,
            'price': price
        }
        
        return aiohttp_jinja2.render_template(template_name, request, context)
    
    async def handle_payment_process(self, request):
        """处理支付表单提交"""
        # 获取表单数据
        data = await request.post()
        plan = data.get('plan', 'free')
        payment_method = data.get('payment_method', '')
        lang = data.get('lang', 'zh-CN')
        
        # 检查用户是否已登录
        is_logged_in = request.cookies.get('is_logged_in') == '1'
        
        if not is_logged_in:
            # 未登录，重定向到登录页面
            return web.HTTPFound(f'/auth/login?lang={lang}')
        
        # 获取用户名
        username = request.cookies.get('username', 'User')
        
        # 这里应该进行实际的支付处理
        # 简化示例：直接返回成功
        
        # 重定向到仪表板
        response = web.HTTPFound(f'/dashboard?lang={lang}')
        
        # 设置套餐cookie
        response.set_cookie('plan', plan, max_age=86400*30, httponly=True)
        
        # 设置成功消息cookie
        if lang == 'en':
            success_message = f'Payment successful. You are now on the {plan.capitalize()} plan.'
        elif lang == 'zh-TW':
            success_message = f'支付成功。您現在使用的是{plan.capitalize()}方案。'
        else:
            success_message = f'支付成功。您现在使用的是{plan.capitalize()}方案。'
        
        response.set_cookie('success_message', success_message, max_age=60, httponly=True)
        
        return response
    
    async def handle_get_works(self, request):
        """处理获取工作列表请求"""
        works = self.model_service.get_works()
        return web.json_response(works)
    
    async def handle_create_work(self, request):
        """处理创建工作请求"""
        try:
            # 解析请求体
            data = await request.json()
            
            # 验证必需参数
            if "first_prompt" not in data:
                return web.json_response({
                    "error": True,
                    "message": "缺少必需参数: first_prompt"
                }, status=400)
            
            # 创建工作
            work = self.model_service.create_work(data["first_prompt"])
            
            return web.json_response(work)
        except json.JSONDecodeError:
            return web.json_response({
                "error": True,
                "message": "无效的JSON格式"
            }, status=400)
        except Exception as e:
            logger.exception(f"创建工作时发生错误: {str(e)}")
            return web.json_response({
                "error": True,
                "message": f"服务器内部错误: {str(e)}"
            }, status=500)
    
    async def handle_get_operations(self, request):
        """处理获取操作历史请求"""
        # 获取查询参数
        work_id = request.query.get('work_id')
        
        operations = self.model_service.get_operations(work_id)
        return web.json_response(operations)
    
    async def handle_get_recordings(self, request):
        """处理获取录屏列表请求"""
        # 获取查询参数
        work_id = request.query.get('work_id')
        
        recordings = self.model_service.get_recordings(work_id)
        return web.json_response(recordings)
    
    async def handle_upload_recording(self, request):
        """处理上传录屏请求"""
        try:
            # 解析multipart表单
            reader = await request.multipart()
            
            # 获取工作ID
            field = await reader.next()
            if field.name != 'work_id':
                return web.json_response({
                    "error": True,
                    "message": "缺少必需参数: work_id"
                }, status=400)
            
            work_id = await field.text()
            
            # 获取文件
            field = await reader.next()
            if field.name != 'file':
                return web.json_response({
                    "error": True,
                    "message": "缺少必需参数: file"
                }, status=400)
            
            filename = field.filename
            file_data = await field.read()
            
            # 保存录屏
            recording = self.model_service.save_recording(work_id, file_data, filename)
            
            return web.json_response(recording)
        except Exception as e:
            logger.exception(f"上传录屏时发生错误: {str(e)}")
            return web.json_response({
                "error": True,
                "message": f"服务器内部错误: {str(e)}"
            }, status=500)
    
    async def handle_send_prompt(self, request):
        """处理发送指令请求"""
        try:
            # 解析请求体
            data = await request.json()
            
            # 验证参数
            try:
                params = self.model_service.validate_parameters(data)
            except ValueError as e:
                return web.json_response({
                    "error": True,
                    "message": str(e)
                }, status=400)
            
            # 生成文本
            if params["stream"]:
                # 流式响应
                response = web.StreamResponse(
                    status=200,
                    reason='OK',
                    headers={'Content-Type': 'text/event-stream'}
                )
                await response.prepare(request)
                
                async for chunk in await self.model_service.generate_text(**params):
                    await response.write(f"data: {json.dumps({'content': chunk})}\n\n".encode('utf-8'))
                
                await response.write_eof()
                return response
            else:
                # 非流式响应
                completion = await self.model_service.generate_text(**params)
                return web.json_response({
                    "completion": completion
                })
        except json.JSONDecodeError:
            return web.json_response({
                "error": True,
                "message": "无效的JSON格式"
            }, status=400)
        except Exception as e:
            logger.exception(f"发送指令时发生错误: {str(e)}")
            return web.json_response({
                "error": True,
                "message": f"服务器内部错误: {str(e)}"
            }, status=500)

async def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='云侧大模型服务器')
    parser.add_argument('--host', type=str, default=DEFAULT_HOST, help=f'监听主机 (默认: {DEFAULT_HOST})')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'监听端口 (默认: {DEFAULT_PORT})')
    parser.add_argument('--llama-host', type=str, default=DEFAULT_LLAMA_HOST, help=f'llamaserver主机 (默认: {DEFAULT_LLAMA_HOST})')
    parser.add_argument('--llama-port', type=int, default=DEFAULT_LLAMA_PORT, help=f'llamaserver端口 (默认: {DEFAULT_LLAMA_PORT})')
    args = parser.parse_args()
    
    # 创建服务器实例
    server = ModelServer(args.host, args.port, args.llama_host, args.llama_port)
    
    # 启动服务器
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    
    logger.info(f"启动服务器: http://{args.host}:{args.port}")
    await site.start()
    
    # 保持服务器运行
    while True:
        await asyncio.sleep(3600)  # 每小时检查一次

if __name__ == "__main__":
    asyncio.run(main())
