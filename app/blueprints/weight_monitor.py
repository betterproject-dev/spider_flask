import requests
from ..extensions import db
from ..models.defects import Defects
from .camera import is_object_detected, last_detection_time
import time

is_on_scale = False # 현재 센서 위에 물체가 있는지 상태를 저장

def process_weight_data(app, data):
  """무게 데이터를 분석하여 불량 여부를 판단하고 DB에 저장하는 전용 함수"""
  from . import camera
  global is_on_scale
  
  DETECTION_VALID_DURATION = 15.0 # 카메라 감지 후 무게 센서까지의 유효시간

  machine_no = data.get("machine_number")
  weight_val = data.get("weight")

  # 무게가 10g미만은 물체가 있든 없든 무시
  if weight_val >= 10:
    if not is_on_scale: # 이전 프레임까지 비어있었다면 '새로운 물체'로 인식
      is_on_scale = True
      # 물체 감지 조건 강화 (카메라 변수 + 시간 직접 체크)
      # 현재 True이거나, 마지막 탐지로부터 2.0초 이내라면 인정
      time_since_last_detect = time.time() - camera.last_detection_time

      if camera.is_object_detected or time_since_last_detect < DETECTION_VALID_DURATION:
        # 정상 범위 판정
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
            requests.get(f"http://localhost:8888/api/stats/update/{machine_no}", timeout=0.5)
            print(f"⚖️ [Weight Logic] {weight_val}g -> {d_type} 처리 완료")
          except Exception as e:
            db.session.rollback()
            print(f"❌ [Weight Logic] DB 저장 에러: {e}")
      else:
        print(f"⚠️ 물체 미감지 판정으로 무시됨 (경과 시간: {time_since_last_detect:.1f}s)")
    else:
      # 이미 센서 위에 물체가 있다고 판단되는 상태 (중복 저장 방지 구간)
      pass
  # 물체가 센서를 완전히 빠져나감
  else:
    if is_on_scale:
      print("물체가 센서를 벗어났습니다. 다음 물체 대기 중...")
      is_on_scale = False
  
  
  

   