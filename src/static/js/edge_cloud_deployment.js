// 端云协同与一键部署功能实现
// 此文件负责实现OurDaily.ai平台的端云协同和一键部署功能

document.addEventListener('DOMContentLoaded', function() {
    // 初始化端云协同适配器
    const edgeCloudAdapter = new EdgeCloudAdapter();
    
    // 注册一键部署按钮事件
    registerDeploymentButtons();
    
    // 注册AI幻灯片助手按钮事件
    registerSlideAssistantButtons();
    
    // 检查用户登录状态
    checkLoginStatus();
});

// 注册一键部署按钮事件
function registerDeploymentButtons() {
    const deployButtons = document.querySelectorAll('.deploy-button');
    
    deployButtons.forEach(button => {
        button.addEventListener('click', async function() {
            // 显示部署进度对话框
            showDeploymentDialog();
            
            // 获取端云协同适配器实例
            const adapter = new EdgeCloudAdapter();
            
            // 开始部署
            const success = await adapter.deployLocalServer();
            
            if (success) {
                updateDeploymentStatus('部署成功！您现在可以使用本地服务了。');
                // 3秒后关闭对话框
                setTimeout(closeDeploymentDialog, 3000);
            } else {
                updateDeploymentStatus('部署失败，请查看控制台获取详细错误信息。');
            }
        });
    });
}

// 显示部署进度对话框
function showDeploymentDialog() {
    // 创建对话框元素
    const dialog = document.createElement('div');
    dialog.id = 'deployment-dialog';
    dialog.className = 'deployment-dialog';
    
    dialog.innerHTML = `
        <div class="deployment-dialog-content">
            <h3>正在部署本地服务</h3>
            <div class="progress-bar">
                <div class="progress-bar-inner"></div>
            </div>
            <p id="deployment-status">正在准备部署环境...</p>
            <button id="close-deployment-dialog" style="display: none;">关闭</button>
        </div>
    `;
    
    // 添加到文档
    document.body.appendChild(dialog);
    
    // 注册关闭按钮事件
    document.getElementById('close-deployment-dialog').addEventListener('click', closeDeploymentDialog);
    
    // 显示对话框
    setTimeout(() => {
        dialog.classList.add('show');
    }, 10);
    
    // 开始进度条动画
    startProgressAnimation();
}

// 关闭部署进度对话框
function closeDeploymentDialog() {
    const dialog = document.getElementById('deployment-dialog');
    if (dialog) {
        dialog.classList.remove('show');
        setTimeout(() => {
            dialog.remove();
        }, 300);
    }
}

// 更新部署状态
function updateDeploymentStatus(status) {
    const statusElement = document.getElementById('deployment-status');
    if (statusElement) {
        statusElement.textContent = status;
    }
    
    // 如果是最终状态，显示关闭按钮
    if (status.includes('成功') || status.includes('失败')) {
        const closeButton = document.getElementById('close-deployment-dialog');
        if (closeButton) {
            closeButton.style.display = 'block';
        }
    }
}

// 开始进度条动画
function startProgressAnimation() {
    const progressBar = document.querySelector('.progress-bar-inner');
    if (progressBar) {
        let width = 0;
        const interval = setInterval(() => {
            if (width >= 90) {
                clearInterval(interval);
            } else {
                width += 1;
                progressBar.style.width = width + '%';
            }
        }, 500);
    }
}

// 注册AI幻灯片助手按钮事件
function registerSlideAssistantButtons() {
    const slideButtons = document.querySelectorAll('.slide-assistant-button');
    
    slideButtons.forEach(button => {
        button.addEventListener('click', function() {
            // 检查用户是否已登录
            if (isUserLoggedIn()) {
                // 已登录，跳转到仪表盘
                window.location.href = '/dashboard';
            } else {
                // 未登录，跳转到登录页面
                window.location.href = '/auth/login';
            }
        });
    });
}

// 检查用户是否已登录
function isUserLoggedIn() {
    // 从cookie或localStorage检查登录状态
    return document.cookie.includes('session_id=');
}

// 检查登录状态
function checkLoginStatus() {
    // 根据登录状态更新UI
    const loginStatus = isUserLoggedIn();
    
    // 更新登录/注册按钮显示
    const loginButtons = document.querySelectorAll('.login-button');
    const registerButtons = document.querySelectorAll('.register-button');
    const userInfoElements = document.querySelectorAll('.user-info');
    
    if (loginStatus) {
        // 已登录，隐藏登录/注册按钮，显示用户信息
        loginButtons.forEach(btn => btn.style.display = 'none');
        registerButtons.forEach(btn => btn.style.display = 'none');
        userInfoElements.forEach(el => el.style.display = 'block');
    } else {
        // 未登录，显示登录/注册按钮，隐藏用户信息
        loginButtons.forEach(btn => btn.style.display = 'block');
        registerButtons.forEach(btn => btn.style.display = 'block');
        userInfoElements.forEach(el => el.style.display = 'none');
    }
}
