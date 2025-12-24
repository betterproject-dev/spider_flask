import os
from flask import Flask
from .config import config
from .extensions import db, migrate, cors

def create_app():
  app = Flask(__name__)

  # 기본은 develop, 배포시 product로 환경변수로 바꾸기
  config_name = os.getenv("FLASK_CONFIG", "develop")
  app.config.from_object(config[config_name])

  db.init_app(app)
  migrate.init_app(app, db)

  # 로그인/쿠키 없으면 supports_credentials=True 굳이 필요 없음
  cors.init_app(app, origins=app.config["CORS_ORIGINS"])

  from .blueprints.camera import bp as camera_bp

  app.register_blueprint(camera_bp, url_prefix='/camera')

  return app