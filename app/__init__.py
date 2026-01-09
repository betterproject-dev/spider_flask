import os
import logging
from flask import Flask
from .config import config
from .extensions import db, migrate, cors, socketio
from .mqtt import init_mqtt

def create_app():
  app = Flask(__name__)

  # 기본은 develop, 배포시 product로 환경변수로 바꾸기
  config_name = os.getenv("FLASK_CONFIG", "develop")
  # 환경에 따른 로그 레벨 설정
  log_level = logging.DEBUG if config_name == "develop" else logging.INFO

  # === 로깅 설정 ===
  logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
  )
  # 카메라 물체 미감지 로그를 ERROR 레벨 이상만 표시(Warning 무시)
  logging.getLogger("ultralytics").setLevel(logging.ERROR)
  # 확인용 로그
  logger = logging.getLogger(__name__)
  logger.info(f"🛠️ 현재 설정 모드: {config_name} (LogLevel: {logging.getLevelName(log_level)})")

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
