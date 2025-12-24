from flask import Flask, render_template
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt
import json

app = Flask(__name__)
socketio = SocketIO(app)

MQTT_BROKER = "soyeon"  # 라즈베리파이 IP 또는 호스트
MQTT_PORT = 1883

# --------------------------
# MQTT 콜백
# --------------------------
def on_connect(client, userdata, flags, rc):
    print("MQTT connected")
    client.subscribe("sensor/#")  # 모든 센서 토픽 구독

def on_message(client, userdata, msg):
    data = msg.payload.decode()
    topic = msg.topic
    # 실시간으로 웹 브라우저에 전송
    socketio.emit('sensor_data', {'topic': topic, 'data': data})

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

