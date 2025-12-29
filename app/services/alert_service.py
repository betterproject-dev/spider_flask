from sqlalchemy import desc
from datetime import datetime
from app import db

from ..models.alert_event import AlertEvent
from ..models.sensors import Sensors
from ..services.danger_service import pick_main_sensor, make_alert_message

def create_stop_event_if_needed(machine_number: int, danger_score: float) -> bool:
  """
    설비가 STOP 상태에 진입했을 때,
    진행 중인 STOP 이벤트가 없으면 AlertEvent를 생성한다.

    Returns:
      bool: 이벤트가 새로 생성되었으면 True, 아니면 False
  """

  # 이미 진행 중인 STOP 이벤트가 있는지 확인 (중복 방지)
  ongoing = (AlertEvent.query
              .filter_by(machine_number=machine_number)
              .filter(AlertEvent.ended_at.is_(None))
              .order_by(desc(AlertEvent.started_at))
              .first()
            )
  
  if ongoing:
    return False # 이미 STOP 이벤트 진행 중

  # 마지막 센서 로그 가져오기 (긴급 시점 스냅샷)
  last_log = (
    Sensors.query
    .filter_by(machine_number=machine_number)
    .order_by(desc(Sensors.id))
    .first()
  )

  if not last_log:
    return False # 센서 로그가 없으면 이벤트 생성 불가
  
  # 어떤 센서가 주 원인인지 선택
  sensor_name, value, limit = pick_main_sensor(last_log)

  # 알림 메시지 생성
  alert_msg = make_alert_message(
    machine_no=machine_number,
    sensor_name=sensor_name,
    value=value,
    limit=limit
  )

  # AlertEvent 생성
  event = AlertEvent(
    machine_number=machine_number,
    level="EMERGENCY",
    danger_score=float(danger_score),
    title=alert_msg["title"],
    message=alert_msg["message"],
    started_at=datetime.now()
  )

  db.session.add(event)
  db.session.commit()

  return True

