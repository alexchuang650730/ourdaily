// 创建Windows和macOS安装包的占位文件
// 这些文件将在实际部署时被替换为真实的安装包
// 仅用于测试下载功能

console.log("Creating placeholder installer files...");

// 这是一个简单的Node.js脚本，用于生成占位安装包
const fs = require('fs');
const path = require('path');

const downloadsDir = path.join(__dirname, 'downloads');

// 确保下载目录存在
if (!fs.existsSync(downloadsDir)) {
    fs.mkdirSync(downloadsDir, { recursive: true });
    console.log(`Created directory: ${downloadsDir}`);
}

// 创建Windows安装包占位文件
const windowsInstallerPath = path.join(downloadsDir, 'OurDaily-Windows-Setup.exe');
fs.writeFileSync(windowsInstallerPath, 'This is a placeholder for the Windows installer.');
console.log(`Created Windows installer placeholder: ${windowsInstallerPath}`);

// 创建macOS安装包占位文件
const macOSInstallerPath = path.join(downloadsDir, 'OurDaily-macOS.dmg');
fs.writeFileSync(macOSInstallerPath, 'This is a placeholder for the macOS installer.');
console.log(`Created macOS installer placeholder: ${macOSInstallerPath}`);

console.log("Placeholder installer files created successfully.");
