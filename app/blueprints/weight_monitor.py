import time
import logging

from app.services.camera_service import CameraService
from app.services.defect_service import DefectService

logger = logging.getLogger(__name__)

is_on_scale = False
last_save_time = 0.0

SAVE_COOLDOWN_SEC = 1.5
ENTER_WEIGHT_TH = 80
EXIT_WEIGHT_TH = 30
EXIT_STABLE_N = 5
exit_count = 0
ENTER_STABLE_N = 3
enter_count = 0

# ✅ FIX: 버퍼가 finalize 되기 직전이면 아주 잠깐 재시도
RETRY_COUNT = 30
RETRY_SLEEP = 0.05  # 1.5초

def _pop_cam_result():
    for _ in range(RETRY_COUNT):
        frame, defects = CameraService.get_current_frame()
        if frame is not None and defects is not None:
            return frame, defects
        time.sleep(RETRY_SLEEP)
    return None, None

def process_weight_data(app, data):
    global is_on_scale, last_save_time, exit_count, enter_count

    machine_no = data.get("machine_number")
    weight_val = data.get("weight")
    now = time.time()

    if machine_no is None or weight_val is None:
        return

    # 내려가면 다음 물체 준비
    if weight_val < EXIT_WEIGHT_TH:
        exit_count += 1
        enter_count = 0
        if exit_count >= EXIT_STABLE_N:
          is_on_scale = False
          exit_count = 0
        return
    else:
        exit_count = 0

    # 이미 처리 중이면 중복 방지
    if is_on_scale:
      return
    
    # 아직 올라온 게 아니면 무시
    if weight_val >= ENTER_WEIGHT_TH:
      enter_count += 1
    else:
      enter_count = 0
      return
    
    if enter_count < ENTER_STABLE_N:
      return
    
    enter_count = 0

    # 쿨다운
    if (now - last_save_time) < SAVE_COOLDOWN_SEC:
        return

    is_on_scale = True
    last_save_time = now

    # ✅ FIX: finished_queue에서 프레임/결함 꺼내기
    buffered_frame, buffered_defects = _pop_cam_result()

    if buffered_frame is None or buffered_defects is None:
        logger.warning("⚠️ finished_queue empty -> fallback to realtime (NO IMAGE SAVE)")

        realtime = CameraService.current_camera_defects.copy()

        # ✅ FIX: realtime['Label']=라벨 감지(True=라벨 있음) -> 불량 여부(True=라벨 없음)
        final_defects = {
            "Label": realtime.get("Label", False),
            "Crushed": realtime.get("Crushed", False),
            "Discolored": realtime.get("Discolored", False),
        }

        final_frame = CameraService.shared_frame
    else:
        final_defects = buffered_defects
        final_frame = buffered_frame

    with app.app_context():
        try:
            DefectService.check_and_save_defect(
                machine_no=machine_no,
                weight_val=weight_val,
                cam_results=final_defects,
                frame=final_frame
            )
        except Exception as e:
            logger.error(f"DB 저장 중 오류 발생: {e}", exc_info=True)
