import logging
from flask import Blueprint, jsonify
from sqlalchemy import desc
from ..utils.send_res import send_res
# 서비스들
from ..services.ml_service import PredictionService
from ..services.danger_service import DangerService
from ..services.danger_score_service import DangerScoreService

# [로그]
logger = logging.getLogger(__name__)

bp = Blueprint('sensormodel', __name__)

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

#예측 후 저장하기 - app.mqtt.py에서 호출할거임
def predictData(machine_number):
  """
  ML 예측
  danger_score 계산
  status 판정
  danger_score 저장
  STOP(70점↑) 또는 누수 발생 시 alert_event 저장
  """

  try:
    # ML 예측
    data, preded_final = PredictionService.predict_next_values(machine_number)

    #위험 점수로 변환
    pred_temp_change = ((preded_final[0][0]-data[9][0])/data[9][0])*100
    pred_hm_change = ((preded_final[0][1]-data[9][1])/data[9][1])*100
    pred_noise_change = ((preded_final[0][2]-data[9][2])/data[9][2])*100

    # danger_score 계산
    danger_score = float(calculate_danger_score(pred_temp_change, pred_hm_change, pred_noise_change))
    logger.debug("====================danger_score==================")
    logger.debug(preded_final)
    logger.debug(danger_score)
    logger.debug("====================danger_score==================")

    # status 판정 (서비스)
    status = DangerService.score_to_level(danger_score)

    # danger_score 저장 (서비스)
    DangerScoreService.save_danger_score(
      machine_number=machine_number,
      danger_score=danger_score
    )

    # 실시간 알림 체크
    from ..models.sensors import Sensors
    from ..services.offline_alert_service import AlertEventService

    # 방금 저장된 가장 최근 로그 가져오기
    last_log = Sensors.query.filter_by(machine_number=machine_number).order_by(desc(Sensors.id)).first()
    if last_log:
      # create_realtime_event_if_needed 내부에서 70점(EMERGENCY_TH) 및 누수 여부를 판단합니다.
      AlertEventService.create_realtime_event_if_needed(machine_number, last_log, danger_score)
    
  except Exception as e:
    logger.error(f"예측 및 알림 생성 중 에러: {e}", exc_info=True)
  
  

#최근 10분간의 위험점수 불러오기
@bp.get('/load_score/<machine_number>')
def load_score(machine_number):
  scores = DangerScoreService.load_danger_score(machine_number)
  
  return send_res(scores, True, '', 200)