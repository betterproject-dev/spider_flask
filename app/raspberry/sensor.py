from flask import Flask, render_template
from flask_socketio import SocketIO 
import paho.mqtt.client as mqtt
import json
from flask_sqlalchemy import SQLAlchemy
import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///spider_db.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
socketio = SocketIO(app)

MQTT_BROKER = "soyeon"  # 라즈베리파이 IP 또는 호스트
MQTT_PORT = 1883

# --------------------------
# 센서 데이터 모델 
# --------------------------
class SensorData(db.Model):
    __tablename__ = 'sensors'
    id = db.Column(db.Integer, primary_key=True)
    machine_number = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    temperature = db.Column(db.Float)
    humidity = db.Column(db.Float)
    noise = db.Column(db.Float)
    leak = db.Column(db.Boolean)
  
# DB 테이블 생성
with app.app_context():
    db.create_all()

# --------------------------
# MQTT 콜백
# --------------------------
def on_connect(client, userdata, flags, rc):
    print("MQTT connected")
    client.subscribe("sensor/#")  # 모든 센서 토픽 구독

def on_message(client, userdata, msg):
    try:
        
      data = json.loads(msg.payload.decode())
      sensor_entry = SensorData(
          machine_number=data.get("machine_number"),
          temperature=data.get("temperature"),
          humidity=data.get("humidity"),
          noise=data.get("noise"),
          leak=data.get("leak")
      )
      db.session.add(sensor_entry)
      db.session.commit()

      # 실시간 웹 전송
      socketio.emit('sensor_data', data)
    except Exception as e:
        print("MQTT message parsing error:", e)

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)

