import os
from flask import Flask
from .config import config
from .extensions import db, migrate, cors, socketio
from .mqtt import init_mqtt

def create_app():
  app = Flask(__name__)

  # 기본은 develop, 배포시 product로 환경변수로 바꾸기
  config_name = os.getenv("FLASK_CONFIG", "develop")
  app.config.from_object(config[config_name])
  # 배경 작업이 중복 실행되지 않도록 체크하는 변수
  app.config['BG_TASK_STARTED'] = False

  db.init_app(app)
  migrate.init_app(app, db)
  socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

  cors.init_app(app, resources={r"/*": {"origins": "*"}})
  
  from .blueprints.sensormodel import bp as sensormodel_bp

  app.mqtt_client = init_mqtt(app)
  
  # === blueprints ===
  from .blueprints.camera import bp as camera_bp
  from .blueprints.sensormodel import bp as sensormodel_bp
	
  app.register_blueprint(camera_bp, url_prefix='/camera')
  app.register_blueprint(sensormodel_bp, url_prefix='/sensormodel')

  return app
