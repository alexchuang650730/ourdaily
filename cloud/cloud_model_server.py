"""
云侧大模型服务器 - 基于新接口规范实现，集成Jinja2模板渲染

此模块实现了云侧大模型服务器，提供以下功能：
1. 用户认证（登录、注册）
2. 首页和仪表盘页面渲染
3. 工作列表管理
4. 操作历史记录
5. 录屏文件管理
6. 付费功能

作者: Manus
日期: 2025-05-18
"""

import os
import json
import logging
import argparse
import asyncio
import aiohttp
import aiohttp_jinja2
import jinja2
from aiohttp import web
import uuid
import time
from datetime import datetime
import base64

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('cloud_model_server')

class ModelServer:
    def __init__(self, host, port, llama_host=None, llama_port=None):
        self.host = host
        self.port = port
        self.llama_host = llama_host
        self.llama_port = llama_port
        self.llama_url = f"http://{llama_host}:{llama_port}/completion" if llama_host and llama_port else None
        
        # 数据存储路径
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
        self.recordings_dir = os.path.join(self.data_dir, 'recordings')
        
        # 确保目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.recordings_dir, exist_ok=True)
        
        # 工作列表和操作历史
        self.works_file = os.path.join(self.data_dir, 'works.json')
        self.operations_file = os.path.join(self.data_dir, 'operations.json')
        
        # 加载数据
        self.works = self.load_works()
        self.operations = self.load_operations()
        
        # 用户会话
        self.sessions = {}
        
        # 初始化应用
        self.app = web.Application()
        
        # 设置Jinja2模板
        self.setup_jinja2()
        
        # 设置路由
        self.setup_routes()
        
        logger.info(f"初始化CloudModelService，连接到llamaserver: {self.llama_url}")
        logger.info(f"已加载 {len(self.works)} 个工作和 {len(self.operations)} 条操作记录")

    def setup_jinja2(self):
        """设置Jinja2模板引擎"""
        templates_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'templates')
        if os.path.exists(templates_path) and os.path.isdir(templates_path):
            aiohttp_jinja2.setup(
                self.app, 
                loader=jinja2.FileSystemLoader(templates_path)
            )
        else:
            logger.warning(f"模板目录不存在: {templates_path}")

    def setup_routes(self):
        """设置路由"""
        # 根路径 - 重定向到登录页面
        self.app.router.add_get('/', self.handle_root)
        
        # 首页
        self.app.router.add_get('/index', self.handle_index)
        
        # 认证相关路由
        self.app.router.add_get('/auth/login', self.handle_login_page)
        self.app.router.add_post('/auth/login', self.handle_login)
        self.app.router.add_get('/auth/register', self.handle_register_page)
        self.app.router.add_post('/auth/register', self.handle_register)
        self.app.router.add_get('/auth/logout', self.handle_logout)
        
        # 仪表盘
        self.app.router.add_get('/dashboard', self.handle_dashboard)
        
        # 定价页面
        self.app.router.add_get('/pricing', self.handle_pricing)
        self.app.router.add_get('/payment', self.handle_payment)
        
        # API端点
        self.app.router.add_get('/api/works', self.handle_get_works)
        self.app.router.add_post('/api/works/create', self.handle_create_work)
        self.app.router.add_get('/api/works/{work_id}', self.handle_get_work)
        self.app.router.add_get('/api/operations', self.handle_get_operations)
        self.app.router.add_post('/api/operations/create', self.handle_create_operation)
        self.app.router.add_get('/api/recordings', self.handle_get_recordings)
        self.app.router.add_post('/api/recordings/upload', self.handle_upload_recording)
        
        # 静态文件
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'static')
        if os.path.exists(static_dir) and os.path.isdir(static_dir):
            self.app.router.add_static('/static', static_dir)
        else:
            logger.warning(f"静态文件目录不存在: {static_dir}")
        
        # 录屏文件
        self.app.router.add_static('/recordings', self.recordings_dir)

    async def handle_root(self, request):
        """处理根路径请求，重定向到登录页面"""
        logger.info("收到根路径请求，重定向到登录页面")
        return web.HTTPFound('/auth/login')

    async def handle_index(self, request):
        """处理首页请求"""
        logger.info("收到首页请求")
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template = 'index_en.html'
        elif lang == 'zh-TW':
            template = 'index_zh-TW.html'
        else:
            template = 'index.html'
        
        # 检查用户是否已登录
        session_id = request.cookies.get('session_id')
        is_logged_in = session_id in self.sessions
        
        context = {
            'is_logged_in': is_logged_in,
            'username': self.sessions.get(session_id, {}).get('username', '') if is_logged_in else '',
            'lang': lang
        }
        
        return aiohttp_jinja2.render_template(template, request, context)

    async def handle_login_page(self, request):
        """处理登录页面请求"""
        logger.info("收到登录页面请求")
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template = 'login_en.html'
        elif lang == 'zh-TW':
            template = 'login_zh-TW.html'
        else:
            template = 'login.html'
        
        context = {
            'error_message': '',
            'lang': lang
        }
        
        return aiohttp_jinja2.render_template(template, request, context)

    async def handle_login(self, request):
        """处理登录请求"""
        logger.info("收到登录请求")
        data = await request.post()
        username = data.get('username')
        password = data.get('password')
        lang = data.get('lang', 'zh-CN')
        
        # 简单的用户验证（实际应用中应使用数据库和加密密码）
        if username == 'admin' and password == 'admin':
            # 创建会话
            session_id = str(uuid.uuid4())
            self.sessions[session_id] = {
                'username': username,
                'login_time': time.time()
            }
            
            # 设置cookie并重定向到仪表盘
            response = web.HTTPFound('/dashboard')
            response.set_cookie('session_id', session_id)
            return response
        else:
            # 登录失败
            if lang == 'en':
                template = 'login_en.html'
                error_message = 'Invalid username or password'
            elif lang == 'zh-TW':
                template = 'login_zh-TW.html'
                error_message = '用戶名或密碼無效'
            else:
                template = 'login.html'
                error_message = '用户名或密码无效'
            
            context = {
                'error_message': error_message,
                'lang': lang
            }
            
            return aiohttp_jinja2.render_template(template, request, context)

    async def handle_register_page(self, request):
        """处理注册页面请求"""
        logger.info("收到注册页面请求")
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template = 'register_en.html'
        elif lang == 'zh-TW':
            template = 'register_zh-TW.html'
        else:
            template = 'register.html'
        
        context = {
            'error_message': '',
            'lang': lang
        }
        
        return aiohttp_jinja2.render_template(template, request, context)

    async def handle_register(self, request):
        """处理注册请求"""
        logger.info("收到注册请求")
        data = await request.post()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        confirm_password = data.get('confirm_password')
        lang = data.get('lang', 'zh-CN')
        
        # 验证输入
        if not username or not email or not password:
            if lang == 'en':
                template = 'register_en.html'
                error_message = 'All fields are required'
            elif lang == 'zh-TW':
                template = 'register_zh-TW.html'
                error_message = '所有欄位都是必填的'
            else:
                template = 'register.html'
                error_message = '所有字段都是必填的'
            
            context = {
                'error_message': error_message,
                'lang': lang
            }
            
            return aiohttp_jinja2.render_template(template, request, context)
        
        if password != confirm_password:
            if lang == 'en':
                template = 'register_en.html'
                error_message = 'Passwords do not match'
            elif lang == 'zh-TW':
                template = 'register_zh-TW.html'
                error_message = '密碼不匹配'
            else:
                template = 'register.html'
                error_message = '密码不匹配'
            
            context = {
                'error_message': error_message,
                'lang': lang
            }
            
            return aiohttp_jinja2.render_template(template, request, context)
        
        # 创建会话（实际应用中应将用户信息保存到数据库）
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            'username': username,
            'email': email,
            'login_time': time.time()
        }
        
        # 设置cookie并重定向到仪表盘
        response = web.HTTPFound('/dashboard')
        response.set_cookie('session_id', session_id)
        return response

    async def handle_logout(self, request):
        """处理登出请求"""
        logger.info("收到登出请求")
        session_id = request.cookies.get('session_id')
        
        if session_id in self.sessions:
            del self.sessions[session_id]
        
        # 清除cookie并重定向到登录页面
        response = web.HTTPFound('/auth/login')
        response.del_cookie('session_id')
        return response

    async def handle_dashboard(self, request):
        """处理仪表盘页面请求"""
        logger.info("收到仪表盘页面请求")
        
        # 检查用户是否已登录
        session_id = request.cookies.get('session_id')
        if session_id not in self.sessions:
            return web.HTTPFound('/auth/login')
        
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template = 'dashboard_en.html'
        elif lang == 'zh-TW':
            template = 'dashboard_zh-TW.html'
        else:
            template = 'dashboard.html'
        
        username = self.sessions[session_id]['username']
        
        context = {
            'username': username,
            'works': self.works,
            'operations': self.operations,
            'lang': lang
        }
        
        return aiohttp_jinja2.render_template(template, request, context)

    async def handle_pricing(self, request):
        """处理定价页面请求"""
        logger.info("收到定价页面请求")
        lang = request.query.get('lang', 'zh-CN')
        
        # 根据语言选择模板
        if lang == 'en':
            template = 'pricing_en.html'
        elif lang == 'zh-TW':
            template = 'pricing_zh-TW.html'
        else:
            template = 'pricing.html'
        
        # 检查用户是否已登录
        session_id = request.cookies.get('session_id')
        is_logged_in = session_id in self.sessions
        
        context = {
            'is_logged_in': is_logged_in,
            'username': self.sessions.get(session_id, {}).get('username', '') if is_logged_in else '',
            'lang': lang
        }
        
        return aiohttp_jinja2.render_template(template, request, context)

    async def handle_payment(self, request):
        """处理支付页面请求"""
        logger.info("收到支付页面请求")
        
        # 检查用户是否已登录
        session_id = request.cookies.get('session_id')
        if session_id not in self.sessions:
            return web.HTTPFound('/auth/login')
        
        plan = request.query.get('plan', 'free')
        lang = request.query.get('lang', 'zh-CN')
        
        context = {
            'username': self.sessions[session_id]['username'],
            'plan': plan,
            'lang': lang
        }
        
        return aiohttp_jinja2.render_template('payment.html', request, context)

    async def handle_get_works(self, request):
        """处理获取工作列表请求"""
        logger.info("收到获取工作列表请求")
        return web.json_response(self.works)

    async def handle_create_work(self, request):
        """处理创建工作请求"""
        logger.info("收到创建工作请求")
        data = await request.json()
        
        work_id = str(uuid.uuid4())
        work = {
            'id': work_id,
            'title': data.get('title', '新工作'),
            'first_instruction': data.get('instruction', ''),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        self.works.append(work)
        self.save_works()
        
        return web.json_response(work)

    async def handle_get_work(self, request):
        """处理获取单个工作请求"""
        logger.info("收到获取单个工作请求")
        work_id = request.match_info['work_id']
        
        for work in self.works:
            if work['id'] == work_id:
                return web.json_response(work)
        
        return web.json_response({'error': 'Work not found'}, status=404)

    async def handle_get_operations(self, request):
        """处理获取操作历史请求"""
        logger.info("收到获取操作历史请求")
        work_id = request.query.get('work_id')
        
        if work_id:
            filtered_operations = [op for op in self.operations if op['work_id'] == work_id]
            return web.json_response(filtered_operations)
        else:
            return web.json_response(self.operations)

    async def handle_create_operation(self, request):
        """处理创建操作记录请求"""
        logger.info("收到创建操作记录请求")
        data = await request.json()
        
        operation_id = str(uuid.uuid4())
        operation = {
            'id': operation_id,
            'work_id': data.get('work_id'),
            'type': data.get('type', 'instruction'),
            'content': data.get('content', ''),
            'created_at': datetime.now().isoformat()
        }
        
        self.operations.append(operation)
        self.save_operations()
        
        return web.json_response(operation)

    async def handle_get_recordings(self, request):
        """处理获取录屏文件列表请求"""
        logger.info("收到获取录屏文件列表请求")
        work_id = request.query.get('work_id')
        
        recordings = []
        for filename in os.listdir(self.recordings_dir):
            if work_id and not filename.startswith(work_id):
                continue
            
            file_path = os.path.join(self.recordings_dir, filename)
            if os.path.isfile(file_path):
                recordings.append({
                    'filename': filename,
                    'url': f'/recordings/{filename}',
                    'size': os.path.getsize(file_path),
                    'created_at': datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                })
        
        return web.json_response(recordings)

    async def handle_upload_recording(self, request):
        """处理上传录屏文件请求"""
        logger.info("收到上传录屏文件请求")
        data = await request.post()
        
        work_id = data.get('work_id')
        recording_file = data.get('file')
        
        if not work_id or not recording_file:
            return web.json_response({'error': 'Missing work_id or file'}, status=400)
        
        # 生成文件名
        filename = f"{work_id}_{int(time.time())}.webm"
        file_path = os.path.join(self.recordings_dir, filename)
        
        # 保存文件
        with open(file_path, 'wb') as f:
            f.write(recording_file.file.read())
        
        return web.json_response({
            'filename': filename,
            'url': f'/recordings/{filename}',
            'size': os.path.getsize(file_path),
            'created_at': datetime.now().isoformat()
        })

    def load_works(self):
        """加载工作列表"""
        if os.path.exists(self.works_file):
            try:
                with open(self.works_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载工作列表失败: {e}")
        
        return []

    def save_works(self):
        """保存工作列表"""
        try:
            with open(self.works_file, 'w', encoding='utf-8') as f:
                json.dump(self.works, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存工作列表失败: {e}")

    def load_operations(self):
        """加载操作历史"""
        if os.path.exists(self.operations_file):
            try:
                with open(self.operations_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载操作历史失败: {e}")
        
        return []

    def save_operations(self):
        """保存操作历史"""
        try:
            with open(self.operations_file, 'w', encoding='utf-8') as f:
                json.dump(self.operations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存操作历史失败: {e}")

    async def start(self):
        """启动服务器"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"服务器已启动，监听 {self.host}:{self.port}")
        
        return runner, site

async def main():
    parser = argparse.ArgumentParser(description='Cloud Model Server')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind')
    parser.add_argument('--llama-host', type=str, default=None, help='LLaMA server host')
    parser.add_argument('--llama-port', type=int, default=None, help='LLaMA server port')
    
    args = parser.parse_args()
    
    server = ModelServer(args.host, args.port, args.llama_host, args.llama_port)
    runner, site = await server.start()
    
    try:
        # 保持服务器运行
        while True:
            await asyncio.sleep(3600)
    finally:
        # 关闭服务器
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
