from sqlalchemy import desc
from app import db
from flask import Blueprint, jsonify
from ..models.sensors import Sensors
from ..models.dangerScore import DangerScore
from ..models.alert_event import AlertEvent
from ..extensions import model, scaler_X, scaler_y
from ..utils.send_res import send_res
import numpy as np
from ..services.danger_service import score_to_level

bp = Blueprint('sensormodel', __name__)

#불러올 칼럼 수
DATA_COUNT = 10

#필요한 만큼의 데이터 불러오기
#return [[온도, 습도, 소음],[온도, 습도, 소음].......]
def get_data(machine_number):
  global DATA_COUNT
  last_10_logs = Sensors.query.filter_by(machine_number=machine_number).order_by(desc(Sensors.id)).limit(DATA_COUNT).all()
  last_10_logs.reverse()
  log_data = [[log.temperature_DS18B20, log.humidity, log.noise] for log in last_10_logs]
  
  return log_data

#위험점수 계산로직 - 테스트해보면서 수치조정필요
def calculate_danger_score(t_ch, h_ch, n_ch):
    # 1. 각 센서별 '최대 변화 허용치' 설정 (이 수치를 넘으면 해당 항목은 100점)
    # 현장 데이터에 맞춰 튜닝이 필요합니다.
    thresholds = {
        'temp': 5.0,   # 1분 만에 5% 변하면 매우 위험
        'hum': 10.0,   # 습도는 온도보다 변화 폭이 클 수 있음
        'noise': 20.0  # 소음은 튈 가능성이 높으므로 20%로 설정
    }

    # 2. 센서별 위험 점수 계산 (절댓값 사용, 최대 100점 제한)
    t_score = min((abs(t_ch) / thresholds['temp']) * 100, 100)
    h_score = min((abs(h_ch) / thresholds['hum']) * 100, 100)
    n_score = min((abs(n_ch) / thresholds['noise']) * 100, 100)

    # 3. 종합 위험 점수 산출 (가중치 적용)
    # 소음과 온도가 결함 평가에 더 중요하다면 가중치를 높입니다.
    weights = {'temp': 0.4, 'hum': 0.1, 'noise': 0.5}
    
    final_score = (t_score * weights['temp']) + \
                  (h_score * weights['hum']) + \
                  (n_score * weights['noise'])
                  
    return round(final_score, 2)

#예측데이터 저장하기 - app.mqtt.py에서 호출할거임
def predictData(machine_number):
  data=get_data(machine_number)
  input_sequence =[]
  
  #첫번째행은 변화율 0
  row = [data[0][0], data[0][1], data[0][2], 0.0, 0.0, 0.0]
  input_sequence.append(row)
  
  #data에 각각 변화율 추가
  for i in range(1,DATA_COUNT):
    curr_data = data[i]
    prev_data = data[i-1]
    
    temp_change_1m = ((curr_data[0]-prev_data[0])/prev_data[0])*100
    hm_change_1m = ((curr_data[1]-prev_data[1])/prev_data[1])*100
    noise_change_1m = ((curr_data[2]-prev_data[2])/prev_data[2])*100
    
    row = [curr_data[0], curr_data[1], curr_data[2], temp_change_1m, hm_change_1m, noise_change_1m]
    input_sequence.append(row)
    
  #스케일링
  scaled_data = scaler_X.transform(input_sequence)
  final_data = np.array([scaled_data])
  
  #예측/역스케일링(복원)
  preded=model.predict(final_data)
  preded_final = scaler_y.inverse_transform(preded)
  
  #위험 점수로 변환
  pred_temp_change = ((preded_final[0][0]-data[9][0])/data[9][0])*100
  pred_hm_change = ((preded_final[0][1]-data[9][1])/data[9][1])*100
  pred_noise_change = ((preded_final[0][2]-data[9][2])/data[9][2])*100
  
  danger_score = calculate_danger_score(pred_temp_change, pred_hm_change, pred_noise_change)
  print("====================danger_score==================")
  print(preded_final)
  print(danger_score)
  print("====================danger_score==================")

  status = score_to_level(danger_score)

  if status == "STOP":
    ongoing = (AlertEvent.query
                .filter_by(machine_number=machine_number)
                .filter(AlertEvent.ended_at.is_(None))
                .first())
    
    if not ongoing:
      envet = AlertEvent(
        machine_number=machine_number,
        level="EMERGENCY",
        danger_score=danger_score,
        title=f"{machine_number}호기 "
      )
  
  ds = DangerScore(dangerScore = float(danger_score), machine_number = machine_number)
  db.session.add(ds)
  db.session.commit()