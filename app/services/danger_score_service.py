import logging
from sqlalchemy import desc
from app import db
from ..models.dangerScore import DangerScore

# [로그]
logger = logging.getLogger(__name__)

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
  except Exception as e:
    logger.error('위험점수 저장 에러가 발생했습니다.')
  return row


def load_danger_score(machine_number):
  last_10_scores = DangerScore.query.filter_by(machine_number=machine_number).order_by(desc(DangerScore.id)).limit(10).all()
  last_10_scores.reverse()
  scores = [score.to_dict() for score in last_10_scores]
  
  return scores