import os
from flask import Flask, redirect, url_for
from flask_session import Session
from config import Config
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.admin import admin_bp
from routes.investments import investments_bp
from routes.referrals import referrals_bp
from routes.football       import football_bp
from routes.contests       import contests_bp
from routes.football import football_bp
from routes.admin_football import admin_football_bp
def create_app():
    
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    Session(app)

    app.register_blueprint(auth_bp,         url_prefix='/auth')
    app.register_blueprint(dashboard_bp,    url_prefix='/dashboard')
    app.register_blueprint(admin_bp,        url_prefix='/admin')
    app.register_blueprint(investments_bp,  url_prefix='/investments')
    app.register_blueprint(referrals_bp,    url_prefix='/referrals')
    app.register_blueprint(football_bp,       url_prefix='/football')
    app.register_blueprint(contests_bp,       url_prefix='/contests')
    app.register_blueprint(football_bp, url_prefix="/football")
    app.register_blueprint(admin_football_bp, url_prefix='/admin/football')
    app.register_blueprint(football_bp)
    
    from routes.football import football_bp

    @app.route('/')
    def index():
        return redirect(url_for('auth.login'))

    return app


app = create_app()

from scheduler import start_scheduler
start_scheduler()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
