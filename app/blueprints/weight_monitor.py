import time
import logging
import threading
import os

from app.services.camera_service import CameraService
from app.services.defect_service import DefectService

logger = logging.getLogger(__name__)

# =========================
# 머신별 상태 + 락
# =========================
_state_lock = threading.Lock()
_state = {}

# =========================
# 파라미터
# =========================
ENTER_WEIGHT_TH = 80
REARM_WEIGHT_TH = 50 # 50g 미만
EXIT_STABLE_N = 3 # 3회 연속

SAVE_COOLDOWN_SEC = 1.0  # ⭐ 중복 저장 방지 쿨타임

RETRY_COUNT = 30
RETRY_SLEEP = 0.05

# finished_queue 데이터 유효시간
QUEUE_DATA_MAX_AGE = 12.0  # ⭐ 카메라-센서 거리가 8~9초이므로 12초로 설정

def _get_state(machine_no: int):
    st = _state.get(machine_no)
    if not st:
        st = {"armed": True, "exit_count": 0, "last_save": 0.0}
        _state[machine_no] = st
    return st

def _pop_cam_result():
    """
    finished_queue에서 데이터를 가져오되, 
    너무 오래된 것은 버리고 최신 것만 사용
    """
    now = time.time()
    
    for _ in range(RETRY_COUNT):
        frame, defects, timestamp = CameraService.get_current_frame_with_timestamp()
        
        if frame is not None and defects is not None:
            age = now - timestamp
            if age > QUEUE_DATA_MAX_AGE:
                logger.warning(
                    f"[STALE_DATA] 큐에서 가져온 데이터가 {age:.2f}초 전 것 -> 버림"
                )
                continue
            
            logger.info(f"[FRESH_DATA] 큐에서 {age:.2f}초 전 데이터 사용 ✅")
            return frame, defects
        
        time.sleep(RETRY_SLEEP)
    
    return None, None

def process_weight_data(app, data):
    machine_no = data.get("machine_number")
    weight_val = data.get("weight")
    now = time.time()

    if machine_no is None or weight_val is None:
        return

    with _state_lock:
        st = _get_state(int(machine_no))

        # 1) 재무장 조건
        if weight_val < REARM_WEIGHT_TH:
            st["exit_count"] += 1
            if st["exit_count"] >= EXIT_STABLE_N:
                if not st["armed"]:
                    logger.info(
                        f"[REARM] pid={os.getpid()} m={machine_no} w={weight_val:.2f} "
                        f"stable={st['exit_count']} -> armed=True"
                    )
                st["armed"] = True
                st["exit_count"] = 0
            return
        else:
            st["exit_count"] = 0

        # 2) 아직 재무장 안 됐으면 저장 불가
        if not st["armed"]:
            logger.debug(f"[NOT_ARMED] m={machine_no} w={weight_val:.2f} -> skip")
            return

        # 3) ENTER 조건 체크
        if weight_val < ENTER_WEIGHT_TH:
            return

        # 4) 쿨다운 체크
        if (now - st["last_save"]) < SAVE_COOLDOWN_SEC:
            logger.debug(
                f"[COOLDOWN] m={machine_no} w={weight_val:.2f} "
                f"last_save={now - st['last_save']:.2f}s ago -> skip"
            )
            return

        # 5) 저장 확정
        st["armed"] = False
        st["last_save"] = now

        logger.info(
            f"[TRIGGER] pid={os.getpid()} m={machine_no} w={weight_val:.2f} "
            f"-> save once, armed=False"
        )

    # =========================
    # 락 밖에서 카메라 데이터 가져오기
    # =========================
    
    # ⭐ finished_queue 상태 먼저 확인
    queue_size = CameraService.get_finished_queue_size()
    logger.info(f"[QUEUE_CHECK] finished_queue size={queue_size}")
    
    buffered_frame, buffered_defects = _pop_cam_result()

    # ⭐ finished_queue가 비어있으면 실시간 카메라 상태 사용
    if buffered_frame is None or buffered_defects is None:
        logger.warning(
            f"[NO_QUEUE_DATA] m={machine_no} w={weight_val:.2f} "
            f"-> finished_queue 비어있음, 실시간 카메라 상태 사용"
        )
        
        # ⭐ 실시간 카메라에서 물체가 감지되고 있는지 확인
        if CameraService.is_object_detected:
            logger.info("[USE_REALTIME] 실시간 카메라에서 물체 감지 중 ✅")
            realtime = CameraService.current_camera_defects.copy()
            final_defects = {
                "Label": realtime.get("Label", False),
                "Crushed": realtime.get("Crushed", False),
                "Discolored": realtime.get("Discolored", False),
            }
            final_frame = CameraService.shared_frame
        else:
            logger.warning(
                f"[NO_CAMERA_OBJECT] m={machine_no} w={weight_val:.2f} "
                f"-> 카메라에 물체 없음, 저장 안 함 ❌"
            )
            
            # 재무장 복구
            with _state_lock:
                st["armed"] = True
            
            return
    else:
        # finished_queue에서 데이터를 가져온 경우
        final_frame = buffered_frame
        final_defects = buffered_defects

    logger.info(
        f"[SAVE_WITH_CAMERA] m={machine_no} w={weight_val:.2f} "
        f"defects={final_defects} ✅"
    )

    with app.app_context():
        DefectService.check_and_save_defect(
            machine_no=machine_no,
            weight_val=weight_val,
            cam_results=final_defects,
            frame=final_frame
        )