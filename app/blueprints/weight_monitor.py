import requests
from ..extensions import db
from ..models.defects import Defects
from .camera import is_object_detected, last_detection_time
import time

def process_weight_data(app, data):
  """무게 데이터를 분석하여 불량 여부를 판단하고 DB에 저장하는 전용 함수"""
  global is_object_detected
  
  machine_no = data.get("machine_number")
  weight_val = data.get("weight")

  # 무게가 10g미만은 물체가 있든 없든 무시
  if weight_val < 10 or machine_no is None:
    return
  
  # 물체 감지 조건 강화 (카메라 변수 + 시간 직접 체크)
  # 현재 True이거나, 마지막 탐지로부터 2.0초 이내라면 인정
  time_since_last_detect = time.time() - last_detection_time
  
  if not is_object_detected and time_since_last_detect > 2.0:
    print(f"물체 미감지 (시간초과 {time_since_last_detect:.1f}s) - {weight_val}g 무시")
    return

  # 불량 판정 로직 (나중에 범위가 바뀌면 여기만 고치면 됨!)
  is_defect = not (200 <= weight_val <= 220)
  d_type = 'weight' if is_defect else 'Normal'

  with app.app_context():
    try:
      new_defect = Defects(
        defect_type=d_type,
        machine_number=machine_no
      )
      db.session.add(new_defect)
      db.session.commit()
            
      # Spring 통계 갱신 신호
      requests.get(f"http://localhost:8888/api/stats/update/{machine_no}")
      print(f"⚖️ [Weight Logic] {weight_val}g -> {d_type} 처리 완료")
    except Exception as e:
      db.session.rollback()
      print(f"❌ [Weight Logic] DB 저장 에러: {e}")