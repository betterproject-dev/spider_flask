import requests
import logging
from app.extensions import db
from app.models.defects import Defects
from app.services.image_service import ImageService

# 로거 설정
logger = logging.getLogger(__name__)

class DefectService:
  @staticmethod
  def check_and_save_defect(machine_no, weight_val, cam_results, frame):
    """
      무게 데이터와 카메라 분석 결과를 종합하여 불량 여부를 판정하고 DB에 저장합니다.
        
      Args:
        machine_no (int): 설비 번호
        weight_val (float): 센서로부터 측정된 무게 값
        cam_results (dict): 카메라에서 탐지된 불량 항목 (Label, Crushed, Discolored 등)
        frame (numpy.ndarray): 불량 발생 시 저장할 현재 카메라 프레임
            
      Returns:
        Defects: 생성된 불량 기록 객체 (성공 시)
            
      Raises:
        Exception: 데이터베이스 저장 작업 중 오류 발생 시 롤백 후 예외 발생
    """
    is_label_ok = bool(cam_results.get("Label", False))          # True = 라벨 보임(정상)
    is_crushed = bool(cam_results.get("Crushed", False))      # True = 찌그러짐 불량
    is_discolored = bool(cam_results.get("Discolored", False))# True = 변색 불량

    # 불량 판정 로직 (무게 범위: 210g ~ 230g 외에는 에러)
    is_weight_in_range = (210 <= weight_val <= 230)
    if (not is_label_ok) or is_crushed or is_discolored or (not is_weight_in_range):
      final_is_defect = 1 # 불량
    else:
      final_is_defect = 0 # 정상

    # 이미지 저장 처리 (불량인 경우에만 물리 파일로 저장)
    img_url = None
    if final_is_defect == 1 and frame is not None:
      img_url = ImageService.save_defect_image(frame)
      
    # DB 객체 생성 및 저장
    new_defect = Defects(
      Label=not is_label_ok,
      Crushed=is_crushed,
      Discolored=is_discolored,
      weight=not is_weight_in_range,
      is_Defect=bool(final_is_defect),
      image_url=img_url,
      machine_number=machine_no
    )

    try:
      db.session.add(new_defect)
      db.session.commit()
      logger.info(f"[Machine {machine_no}] DB 저장 완료 | ID: {new_defect.id} | 불량: {final_is_defect}")

      # 외부 통계 서버 알림
      try:
        # 타임아웃을 짧게 설정하여 메인 프로세스 지연 방지
        resp = requests.get(f"http://localhost:8888/api/stats/update/{machine_no}", timeout=0.5)
        if resp.status_code == 200:
          logger.info(f"[Machine {machine_no}] 외부 통계 서버 갱신 성공")
      except requests.exceptions.RequestException as e:
        # 통계 서버 연결 실패는 핵심 로직이 아니므로 경고 로그만 남김
        logger.warning(f"[Machine {machine_no}] 통계 서버 연결 실패: {e}")
      return new_defect
    except Exception as e:
      # 오류 발생 시 DB 롤백 및 에러 로그 기록
      db.session.rollback()
      logger.error(f"[Machine {machine_no}] DB 저장 에러: {e}", exc_info=True)
      raise e

