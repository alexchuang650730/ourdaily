from flask import Blueprint, render_template, session, redirect, url_for, request
from datetime import datetime

dashboard_bp = Blueprint("dashboard_route", __name__)

def get_mock_attachments(lang):
    """
    生成模拟的附件数据，根据语言返回不同的内容
    """
    if lang == "en":
        return [
            {
                "icon": "fa-file-alt",
                "title": "Download WorkHub for Collaboration",
                "meta": "Hello, I've received your request, need...",
                "date": "22:19"
            },
            {
                "icon": "fa-file-alt",
                "title": "New Task",
                "meta": "Hello, regarding the AI Image Assistant...",
                "date": "Friday"
            },
            {
                "icon": "fa-file-alt",
                "title": "Desktop App Support for Mac and Win",
                "meta": "You raised a good question. Indeed...",
                "date": "Friday"
            },
            {
                "icon": "fa-file-alt",
                "title": "New Task",
                "meta": "Hello, I've completed your previous...",
                "date": "Friday"
            },
            {
                "icon": "fa-file-alt",
                "title": "Desktop App Support for Mac and Win",
                "meta": "I'm carefully analyzing the link you...",
                "date": "Thursday"
            }
        ]
    elif lang == "zh-TW":
        return [
            {
                "icon": "fa-file-alt",
                "title": "下載WorkHub提升協作效率",
                "meta": "您好，我已收到您的新請求，需...",
                "date": "22:19"
            },
            {
                "icon": "fa-file-alt",
                "title": "New Task",
                "meta": "您好，關於 AI 圖像助手「立即使用」...",
                "date": "週五"
            },
            {
                "icon": "fa-file-alt",
                "title": "完善桌面程式支持Mac和Win",
                "meta": "您提出了一個很好的問題。確實...",
                "date": "週五"
            },
            {
                "icon": "fa-file-alt",
                "title": "New Task",
                "meta": "您好，我已經完成了您先前要求...",
                "date": "週五"
            },
            {
                "icon": "fa-file-alt",
                "title": "完善桌面程式以支持Mac和Win",
                "meta": "我正在仔細分析您提供的豆包鏈...",
                "date": "週四"
            }
        ]
    else:  # 默认简体中文
        return [
            {
                "icon": "fa-file-alt",
                "title": "下载WorkHub提升协作效率",
                "meta": "您好，我已收到您的新请求，需...",
                "date": "22:19"
            },
            {
                "icon": "fa-file-alt",
                "title": "New Task",
                "meta": "您好，关于 AI 图像助手「立即使用」...",
                "date": "周五"
            },
            {
                "icon": "fa-file-alt",
                "title": "完善桌面程式支持Mac和Win",
                "meta": "您提出了一个很好的问题。确实...",
                "date": "周五"
            },
            {
                "icon": "fa-file-alt",
                "title": "New Task",
                "meta": "您好，我已经完成了您先前要求...",
                "date": "周五"
            },
            {
                "icon": "fa-file-alt",
                "title": "完善桌面程式以支持Mac和Win",
                "meta": "我正在仔细分析您提供的豆包链...",
                "date": "周四"
            }
        ]

@dashboard_bp.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        # User not logged in, redirect to login page, preserving language if possible
        lang = session.get("lang", request.args.get("lang", "zh-CN"))
        return redirect(url_for("auth.login", lang=lang))
    
    username = session.get("username", "User")
    lang = session.get("lang", "zh-CN") # Get language from session, default to zh-CN
    
    # 获取对应语言的附件数据
    attachments = get_mock_attachments(lang)

    if lang == "en":
        return render_template("dashboard_en.html", username=username, attachments=attachments)
    elif lang == "zh-TW":
        return render_template("dashboard_zh-TW.html", username=username, attachments=attachments)
    return render_template("dashboard.html", username=username, attachments=attachments)

