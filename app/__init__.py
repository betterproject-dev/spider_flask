import os
from flask import Flask
from .config import config
from .extensions import db, migrate, cors, socketio
import paho.mqtt.client as mqtt
import json
from app.models.machines import Machines
from app.models.sensors import Sensors

def create_app():
  app = Flask(__name__)

  # 기본은 develop, 배포시 product로 환경변수로 바꾸기
  config_name = os.getenv("FLASK_CONFIG", "develop")
  app.config.from_object(config[config_name])
  # 배경 작업이 중복 실행되지 않도록 체크하는 변수
  app.config['BG_TASK_STARTED'] = False

  db.init_app(app)
  migrate.init_app(app, db)

  socketio.init_app(app, cors_allowed_origins="*")

  # 로그인/쿠키 없으면 supports_credentials=True 굳이 필요 없음
  cors.init_app(app, origins=app.config["CORS_ORIGINS"])
  
  from .blueprints.sensormodel import bp as sensormodel_bp

  # ==============================
  # MQTT 설정
  # ==============================
  MQTT_BROKER = "soyeon"
  MQTT_PORT = 1883

  # ==============================
  # MQTT 콜백
  # ==============================
  def on_connect(client, userdata, flags, rc):
      print("MQTT connected (code:", rc, ")")
      client.subscribe("sensor/#")

  def on_message(client, userdata, msg):
      print("MQTT message received:", msg.topic, msg.payload)
      try:
          data = json.loads(msg.payload.decode())
          print("Parsed JSON:", data)

          # 필수 값 체크
          machine_no = data.get("machine_number")
          if machine_no is None:
              print("⚠️ MQTT 메시지에 machine_number 정보가 없습니다.")
              return

          # DB 저장
          # 명시적으로 Flask Application Context 안에서 DB 작업 수행
          with app.app_context():
            db.create_all()

            # 자동 머신 생성
            if not Machines.query.get(1):
               m = Machines(id=1, location="unknown")
               db.session.add(m)
               db.session.commit()
               
            sensor_entry = Sensors(
                machine_number=machine_no,
                temperature=data.get("temperature"),
                humidity=data.get("humidity"),
                noise=data.get("noise"),
                leak=data.get("leak")
            )
            
            # 너무 많이 저장돼서 임시로  db 주석처리 해놓음!
            # db.session.add(sensor_entry)
            # db.session.commit()
            
            socketio.emit("sensor_data", {
							'temperature' : sensor_entry.temperature,
							'humidity' : sensor_entry.humidity,
							'noise' : sensor_entry.noise,
							'leak' : sensor_entry.leak,
              'timestamp' : sensor_entry.created_at.strftime('%H:%M:%S')
						})

      except Exception as e:
          print("MQTT message parsing / DB error:", e)

  # ==============================
  # MQTT 클라이언트
  # ==============================
  mqtt_client = mqtt.Client()
  mqtt_client.on_connect = on_connect
  mqtt_client.on_message = on_message
  mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
  mqtt_client.loop_start()
  
  # === blueprints ===
  from .blueprints.test import bp as test_bp # 테스트용(삭제)
  app.register_blueprint(test_bp, url_prefix='/test') # 테스트용(삭제)
	
  from .blueprints.camera import bp as camera_bp
  app.register_blueprint(camera_bp, url_prefix='/camera')
  app.register_blueprint(sensormodel_bp, url_prefix='/sensormodel')

  return app
