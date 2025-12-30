from app import db
from ..models.dangerScore import DangerScore

def save_danger_score(machine_number: int, danger_score: float | None = None) -> DangerScore:
  """
    위험 점수를 danger_score 테이블에 저장한다.

    Args:
      machine_number (int): 설비(호기) 번호
      danger_score (float): 계산된 위험 점수

    Returns:
      DangerScore: 저장된 ORM 객체
  """

  # 모델 필드명에 맞춰 넣어야 함
  row = DangerScore(
    machine_number=machine_number,
    dangerScore = float(danger_score)
  )

  db.session.add(row)
  db.session.commit()

  return row

