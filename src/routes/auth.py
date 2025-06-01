from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from src.models.user import User
from src.models.user import db

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    lang = request.args.get('lang', 'zh-CN') # Get language from query parameter
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()
        if user:
            if lang == 'en':
                flash("Username already exists", "error")
            elif lang == 'zh-TW':
                flash("使用者名稱已存在", "error")
            else:
                flash("用户名已存在", "error")
            return redirect(url_for("auth.register", lang=lang))

        new_user = User(username=username, password=generate_password_hash(password, method="pbkdf2:sha256"))
        db.session.add(new_user)
        db.session.commit()
        if lang == 'en':
            flash("Registration successful! Please log in.", "success")
        elif lang == 'zh-TW':
            flash("註冊成功！請登入。", "success")
        else:
            flash("注册成功！请登录。", "success")
        return redirect(url_for("auth.login", lang=lang))
    
    if lang == 'en':
        return render_template("register_en.html")
    elif lang == 'zh-TW':
        return render_template("register_zh-TW.html")
    return render_template("register.html")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    lang = request.args.get('lang', 'zh-CN') # Get language from query parameter
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password, password):
            if lang == 'en':
                flash("Incorrect username or password", "error")
            elif lang == 'zh-TW':
                flash("使用者名稱或密碼錯誤", "error")
            else:
                flash("用户名或密码错误", "error")
            return redirect(url_for("auth.login", lang=lang))

        session["user_id"] = user.id
        session["username"] = user.username
        session["lang"] = lang # Store language in session
        
        if lang == 'en':
            flash("Login successful!", "success")
        elif lang == 'zh-TW':
            flash("登入成功！", "success")
        else:
            flash("登录成功！", "success")
        return redirect(url_for("dashboard_route.dashboard")) 

    if lang == 'en':
        return render_template("login_en.html")
    elif lang == 'zh-TW':
        return render_template("login_zh-TW.html")
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    lang = session.get("lang", 'zh-CN') # Get lang from session or default
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("lang", None)
    if lang == 'en':
        flash("You have been logged out.", "success")
    elif lang == 'zh-TW':
        flash("您已成功登出。", "success")
    else:
        flash("您已成功登出。", "success")
    return redirect(url_for("main.home", lang=lang))

