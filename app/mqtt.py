import json
import paho.mqtt.client as mqtt
from flask import current_app

from .extensions import db
from .models.machines import Machines
from .models.sensors import Sensors
from .blueprints.sensormodel import predictData


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

    return client


def on_connect(client, userdata, flags, rc):
    print("MQTT connected (code:", rc, ")")
    client.subscribe("sensor/#")


def on_message(client, userdata, msg):
    app = userdata["app"]

    try:
        data = json.loads(msg.payload.decode())
        print("Parsed JSON:", data)

        machine_no = data.get("machine_number")
        if machine_no is None:
            print("⚠️ machine_number 없음")
            return

        with app.app_context():
            # 머신 자동 생성
            if not Machines.query.get(machine_no):
                m = Machines(id=machine_no, location="unknown")
                db.session.add(m)
                db.session.commit()

            temp_ds = data.get("temperature_DS18B20")
            humidity = data.get("humidity")
            noise = data.get("noise")

            # 필수 센서 중 하나라도 None이면 저장 안 함
            if temp_ds is None or humidity is None or noise is None :
                print("⚠️ 센서 값 중 NULL 있음 → DB 저장 안 함")
                return

            sensor = Sensors(
                machine_number=machine_no,
                temperature_DS18B20=data.get("temperature_DS18B20"),
                humidity=data.get("humidity"),
                noise=data.get("noise"),
                leak=bool("leak"),
            )

            db.session.add(sensor)
            db.session.commit()
            # predictData(machine_no) #센서 값 저장되면 바로 위험점수 계산하여 db저장합니다.

    except Exception as e:
        print("MQTT 처리 오류:", e)
