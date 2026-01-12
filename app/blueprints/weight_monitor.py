import time
import logging
from app.services.camera_service import CameraService
from app.services.defect_service import DefectService

is_on_scale = False # 현재 센서 위에 물체가 있는지 상태를 저장
logger = logging.getLogger(__name__)
last_save_time = 0

def process_weight_data(app, data):
  """무게 데이터를 분석하여 불량 여부를 판단하고 DB에 저장하는 전용 함수"""
  global is_on_scale, last_save_time
  
  DETECTION_VALID_DURATION = 15.0 # 카메라 감지 후 무게 센서까지의 유효시간

  machine_no = data.get("machine_number")
  weight_val = data.get("weight")
  current_time = time.time()

  # 무게가 80g미만은 물체가 있든 없든 무시
  if weight_val >= 80:
    if not is_on_scale and (current_time - last_save_time > 2.0): # 이전 프레임까지 비어있었다면 '새로운 물체'로 인식
      is_on_scale = True
      last_save_time = current_time

      buffered_frame, buffered_defects = CameraService.get_current_frame()
      logger.debug(f"[Machine {machine_no}] 새로운 물체 감지 (무게: {weight_val}g)")

      final_defects = buffered_defects if buffered_defects is not None else CameraService.current_camera_defects

      # 물체 감지 조건 강화 (카메라 변수 + 시간 직접 체크)
      # 현재 True이거나, 마지막 탐지로부터 2.0초 이내라면 인정
      time_since_last_detect = time.time() - CameraService.last_detection_time
      is_valid_detection = CameraService.is_object_detected or (time_since_last_detect < DETECTION_VALID_DURATION)

      if is_valid_detection:
        with app.app_context():
          try:
            DefectService.check_and_save_defect(
              machine_no=machine_no,
              weight_val=weight_val,
              cam_results=final_defects,
              frame=buffered_frame
            )
            # 초기화
            CameraService.reset_camera_defects()
            logger.info(f"[Machine {machine_no}] 데이터 저장 및 카메라 상태 초기화 완료")
          except Exception :
            # 서비스 내부에서 이미 로깅함
            pass
      else:
        logger.warning(f"[Machine {machine_no}] 탐지 유효시가 초과({time_since_last_detect:.1f}s). 저장 생략")
  elif weight_val < 30: # 무게가 30g 이하로 내려가야 다음 물체 인식 가능)
    is_on_scale = False
   