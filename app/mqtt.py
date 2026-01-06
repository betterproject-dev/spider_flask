import json
import paho.mqtt.client as mqtt

from .extensions import db, socketio
from .models.machines import Machines
from .models.sensors import Sensors
from .blueprints.sensormodel import predictData
import threading
from .services.offline_alert_service import create_offline_event_if_needed

import time

from .blueprints.weight_monitor import process_weight_data

OFFLINE_CHECK_INTERVAL = 30 

def offline_watch_loop(app):
    while True:
        try:
            with app.app_context():
                # 지금 1호기만이면 1만
                create_offline_event_if_needed(1)
        except Exception as e:
            print("offline_watch_loop error: ", e)

        time.sleep(OFFLINE_CHECK_INTERVAL)


def init_mqtt(app):
    client = mqtt.Client()

    # Flask app 전달
    client.user_data_set({"app": app})

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(
        app.config["MQTT_BROKER"],
        app.config.get("MQTT_PORT", 1883),
        60
    )
    client.loop_start()

    # 여기에서 offline 감시 스레드 시작
    t = threading.Thread(target=offline_watch_loop, args=(app,), daemon=True)
    t.start()

    return client


def on_connect(client, userdata, flags, rc):
    print("MQTT connected (code:", rc, ")")
    client.subscribe("sensor/#")

# DB 저장 주기 조절하기 위한 시간 저장 변수
last_save_time = 0

def on_message(client, userdata, msg):
    global last_save_time
    app = userdata["app"]

    try:
        data = json.loads(msg.payload.decode())
        print("Parsed JSON:", data)
        current_time = time.time()  # 현재 시간

        machine_no = data.get("machine_number")
        if machine_no is None:
            print("⚠️ machine_number 없음")
            return

        temp = data.get("temperature") # 공장 온도 (온습도 센서)
        temp_ds = data.get("temperature_DS18B20") # 기계 온도 (부착형 온도센서)
        humidity = data.get("humidity")
        noise = data.get("noise")
        leak = data.get("leak")

        # 필수 센서 중 하나라도 None이면 소켓 전송 & DB 저장 안 함
        if temp_ds is None or humidity is None or noise is None or leak is None:
            print("⚠️ 센서 값 중 NULL 있음 → 소켓 전송 및 DB 저장 안 함")
            return
        
        # 실시간 차트용
        display_time = time.strftime('%H:%M:%S', time.localtime(current_time))
        
        # 소켓 전송
        socketio.emit("sensor_data", {
          'temperature' : temp,
          'temperature_DS18B20' : temp_ds,
          'humidity' : humidity,
          'noise' : noise,
          'leak' : leak,
          'timestamp' : display_time
        })

        if "weight" in data:
            process_weight_data(app, data)

        # 마지막 저장 후 60초가 지나지 않았으면 리턴 (저장x)
        if current_time - last_save_time < 60:
          return

        # 60초가 지났으면 저장o
        with app.app_context():
            # 머신 자동 생성
            if not Machines.query.get(machine_no):
                m = Machines(id=machine_no, location="unknown")
                db.session.add(m)
                db.session.commit()

            sensor = Sensors(
                machine_number=machine_no,
                temperature_DS18B20=temp_ds,
                humidity=humidity,
                noise=noise,
                leak=leak
            )

            db.session.add(sensor)
            db.session.commit()
            # 마지막 저장시간 업데이트
            last_save_time = current_time
            predictData(machine_no) # 센서 값 저장되면 바로 위험점수 계산하여 db저장합니다.

    except Exception as e:
        print("MQTT 처리 오류:", e)
