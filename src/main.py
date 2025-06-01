import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, request, session # Added session
from src.models.user import db
from src.routes.auth import auth_bp
from src.routes.dashboard_routes import dashboard_bp # Import the dashboard blueprint

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "your_very_secret_key_here" # Change this!

# Configure the SQLAlchemy part of the app instance
# Using SQLite for simplicity. Ensure the instance folder exists.
instance_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "instance")
os.makedirs(instance_path, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(instance_path, 'app.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize extensions
db.init_app(app)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp) # Register the dashboard blueprint

# Create database tables if they don't exist
with app.app_context():
    db.create_all()

# Define a simple home route for main_routes.home
@app.route("/")
def home():
    lang = request.args.get('lang')
    if not lang:
        lang = session.get('lang', 'zh-CN') # Get lang from session if not in query, default to zh-CN
    else:
        session['lang'] = lang # Store lang in session if provided in query

    if lang == 'en':
        template_name = "index_en.html"
    elif lang == 'zh-TW':
        template_name = "index_zh-TW.html"
    else: # Default to zh-CN or if lang is not recognized
        template_name = "index.html" 
        
    return render_template(template_name)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

