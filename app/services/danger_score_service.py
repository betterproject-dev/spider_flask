import logging
from sqlalchemy import desc
from app import db
from ..models.dangerScore import DangerScore
import logging

logger = logging.getLogger(__name__)

class DangerScoreService:
  @staticmethod
  def save_danger_score(machine_number: int, danger_score: float | None = None) -> DangerScore:
    """
      위험 점수를 danger_score 테이블에 저장한다.

      Args:
        machine_number (int): 설비(호기) 번호
        danger_score (float): 계산된 위험 점수

      Returns:
        DangerScore: 저장된 ORM 객체
    """
    try:
      # 모델 필드명에 맞춰 넣어야 함
      row = DangerScore(
        machine_number=machine_number,
        dangerScore = float(danger_score)
      )

      db.session.add(row)
      db.session.commit()
      return row
    except Exception as e:
      db.session.rollback()
      logger.error(f"[Machine {machine_number}] 위험점수 저장 실패: {e}", exc_info=True)
      return None

  @staticmethod
  def load_danger_score(machine_number):
    """특정 설비의 최근 10개 위험 점수를 가져온다."""
    try:
      last_10_scores = DangerScore.query.filter_by(machine_number=machine_number).order_by(desc(DangerScore.id)).limit(10).all()
      last_10_scores.reverse()
      scores = [score.to_dict() for score in last_10_scores]
      
      return scores
    except Exception as e:
      logger.error(f"[Machine {machine_number}] 위험점수 로드 실패: {e}")
      return []