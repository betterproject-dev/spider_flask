import os
import uuid
import cv2
import logging

# 로거 설정
logger = logging.getLogger(__name__)

class ImageService:
  @staticmethod
  def save_defect_image(frame):
    """불량 발생 시 현재 프레임을 물리 파일로 저장"""
    if frame is None:
      logger.warning("저장할 프레임이 없습니다(None).")
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
      logger.info(f"불량 이미지 저장 성공: {file_path}")
      return f"/static/uploads/defects/{file_name}"
    except Exception as e:
      logger.error(f"이미지 저장 중 예외 발생 : {e}", exc_info=True)
      return None