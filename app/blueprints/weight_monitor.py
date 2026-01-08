import os
import time
import uuid
import cv2
import requests
from app.extensions import db
from app.models.defects import Defects

is_on_scale = False # 현재 센서 위에 물체가 있는지 상태를 저장

def save_defect_image(frame):
  """불량 발생 시 현재 프레임을 물리 파일로 저장"""
  if frame is None:
    return None
    
  try:
    # 1. 저장 경로 확보
    upload_path = os.path.join(os.getcwd(), 'app', 'static', 'uploads', 'defects')
    os.makedirs(upload_path, exist_ok=True)

    # 2. 고유 파일명 생성
    file_name = f"defect_{uuid.uuid4().hex}.jpg"
    file_path = os.path.join(upload_path, file_name)

    # 3. 이미지 저장 및 웹 경로 반환
    cv2.imwrite(file_path, frame)
    return f"/static/uploads/defects/{file_name}"
  except Exception as e:
    print(f"⚠️ 이미지 저장 실패: {e}")
    return None

def process_weight_data(app, data):
  """무게 데이터를 분석하여 불량 여부를 판단하고 DB에 저장하는 전용 함수"""
  from . import camera
  global is_on_scale
  
  DETECTION_VALID_DURATION = 15.0 # 카메라 감지 후 무게 센서까지의 유효시간

  machine_no = data.get("machine_number")
  weight_val = data.get("weight")

  # 무게가 80g미만은 물체가 있든 없든 무시
  if weight_val >= 1.0:
    #if not is_on_scale: # 이전 프레임까지 비어있었다면 '새로운 물체'로 인식
      is_on_scale = True
      # 물체 감지 조건 강화 (카메라 변수 + 시간 직접 체크)
      # 현재 True이거나, 마지막 탐지로부터 2.0초 이내라면 인정
      time_since_last_detect = time.time() - camera.last_detection_time
      is_valid_detection = camera.is_object_detected or (time_since_last_detect < DETECTION_VALID_DURATION)

      if is_valid_detection:
        # 정상 범위 판정
        is_weight_error = not (1.0 <= weight_val <= 3.0)
        cam_results = camera.current_camera_defects
        final_is_defect = any(cam_results.values()) or is_weight_error

        img_url = None
        if final_is_defect:
          current_frame = camera.get_current_frame()
          img_url = save_defect_image(current_frame)

        with app.app_context():
          try:
            new_defect = Defects(
            Label=cam_results.get('Label', False),
            Crushed=cam_results.get('Crushed', False),
            Discolored=cam_results.get('Discolored', False),
            weight=is_weight_error,
            is_Defect=final_is_defect,
            image_url=img_url,
            machine_number=machine_no
            )
            db.session.add(new_defect)
            db.session.commit()
            
            camera.current_camera_defects = {'Label':False, 'Crushed':False, 'Discolored':False}
            # Spring 통계 갱신 신호
            try:
              requests.get(f"http://localhost:8888/api/stats/update/{machine_no}", timeout=0.5)
              print(f"저장 완료: 불량({final_is_defect}), 이미지({img_url})")
            except requests.exceptions.RequestException:
              pass
            print(f"[ID:{machine_no}] 저장 완료 | 불량: {final_is_defect} | 이미지: {img_url}")
          except Exception as e:
            db.session.rollback()
            print(f"DB 저장 에러: {e}")
      else:
        print(f"탐지 유효시간 초과({time_since_last_detect:.1f}s). 저장을 건너뜁니다.")
  else:
    if is_on_scale:
      print("물체가 센서를 벗어났습니다. 다음 물체 대기 중...")
      is_on_scale = False

   