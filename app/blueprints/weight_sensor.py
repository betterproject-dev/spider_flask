from flask import Flask, render_template, request, jsonify, Blueprint
import paho.mqtt.client as mqtt
import json

bp = Blueprint('sensor', __name__)

# MQTT 설정, .env에 넣어주는게 좋다
# 브로커 ip주소 ( 우리는 라즈베리파이를 브로커로 사용할거임 )
MQTT_BROKER = 'soyeon'
MQTT_PORT = 1883
MQTT_TOPIC = 'sensor/weight'

# 최신 무게 데이터를 저장할 변수
latest_weight_data = {"weight": 0, "time": "-"}

# 메시지를 받았을 때 실행되는 콜백 함수
def on_message(client, userdata, msg):
  global latest_weight_data
  try:
    latest_weight_data = json.loads(msg.payload.decode())
  except Exception as e:
    print(f"데이터 파싱 오류: {e}")

# MQTT 설정
mqtt_client = mqtt.Client() # userdata도 넣을 수 있음
mqtt_client.on_message = on_message

# mqtt 연결 시도 후 실행되는 콜백 함수
# flags : 상태
# rc : 리턴 1~5 -> 실패
def on_connect(client, userdata, flags, rc):
  if rc == 0:
    print(f"MQTT 브로커에 연결 성공 : {MQTT_BROKER}, {MQTT_PORT}")
    client.subscribe(MQTT_TOPIC)
  else:
    print(f"MQTT 연결 실패")

# 메세지를 발행 후 실행되는 콜백 함수
# mid : id 값
def on_publish(client, userdata, mid):
  print(f"메시지 발행 성공 : {mid}")

# 위에서 만들어둔 콜백함수를 등록
mqtt_client.on_connect = on_connect
mqtt_client.on_publish = on_publish

# MQTT 브로커 연결
try:
  mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60) # 60 : 60초
  mqtt_client.loop_start() # 브로커와 통신할때 자동으로 해주는 쓰레드
except Exception as e:
  print(f"MQTT 연결 오류 : {e}")

@bp.route('/')
def index():
  return render_template('index.html')
  
@bp.route('/api/weight')
def get_weight():
  return jsonify(latest_weight_data)

if __name__ == '__main__':
  bp.run(host='0.0.0.0', debug=True)
