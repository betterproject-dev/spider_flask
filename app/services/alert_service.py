from sqlalchemy import desc, or_
from datetime import datetime, timedelta
from app import db
import json

from ..models.alert_event import AlertEvent
from ..models.sensors import Sensors
from ..services.danger_service import pick_main_sensor, make_alert_message, EMERGENCY_TH

COOLDOWN_SECONDS = 15

def create_stop_event_if_needed(machine_number: int, danger_score: float) -> AlertEvent | None:
  """
    설비가 STOP 상태에 진입했을 때,
    진행 중인 STOP 이벤트가 없으면 AlertEvent를 생성한다.
    - danger_score >= EMERGENCY_TH
    - 또는 누수 감지(leak == 0)

    Returns:
      AlertEvent | None: 새로 생성된 이벤트 객체, 생성되지 않으면 None
  """

  now = datetime.now()

  # 마지막 센서 로그 가져오기 (긴급 시점 스냅샷)
  last_log = (
    Sensors.query
    .filter_by(machine_number=machine_number)
    .order_by(desc(Sensors.id))
    .first()
  )

  if not last_log:
    return None # 센서 로그가 없으면 이벤트 생성 불가
  
  # 누수 감지 (Active Low)
  leak_is_leak = (last_log.leak is False or last_log.leak == 0)

  # 점수 기반 STOP
  score_stop = (danger_score >= EMERGENCY_TH)

  is_leak_trigger = leak_is_leak
  is_score_trigger = score_stop

  # 조건 만족 못하면 이벤트 생성 안 함
  if not (is_leak_trigger or is_score_trigger):
    return None
  
  if is_leak_trigger and not is_score_trigger:
    ongoing_leak = (AlertEvent.query.filter(
            AlertEvent.machine_number == machine_number,
            AlertEvent.level == "EMERGENCY",
            AlertEvent.ended_at == None,
            AlertEvent.title.like("%누수%") # title="누수센서" 보다 유연하게 체크
    )).first()
    if ongoing_leak:
      return None
  
  # 점수 STOP이 있으면 점수 원인(온도/습도/소음)을 우선
  if is_score_trigger:
    sensor_name, value, limit = pick_main_sensor(last_log)
  else:
    sensor_name, value, limit = ("누수센서", 0, 0)
  # 알림 메시지 생성
  alert_msg = make_alert_message(
    machine_no=machine_number,
    sensor_name=sensor_name,
    value=value,
    limit=limit
  )

  # 쿨다운 체크 (점수 기반 중단일 때만)
  if is_score_trigger:
    last_event = (
      AlertEvent.query
        .filter_by(machine_number=machine_number, level="EMERGENCY")
        .filter(AlertEvent.ended_at.is_(None)) 
        .filter(or_(AlertEvent.title.is_(None), ~AlertEvent.title.like("%누수%")))
        .order_by(desc(AlertEvent.started_at))
        .first()
    )
    if last_event:
      within_cd = (now - last_event.started_at) < timedelta(seconds=COOLDOWN_SECONDS)
      if within_cd and last_event.title == alert_msg["title"]:
        print("DEBUG: Within cooldown period. Skipping.")
        return None
      
  snapshot = {
    "temperature": last_log.temperature_DS18B20,
    "humidity": last_log.humidity,
    "noise": last_log.noise,
    "leak": last_log.leak,
    "danger_score": float(danger_score),
    "created_at": last_log.created_at.isoformat() if last_log.created_at else None
  }

  # 데이터 생성 및 저장
  try:
    event = AlertEvent(
      machine_number=machine_number,
      level="EMERGENCY",
      danger_score=float(danger_score),
      title=alert_msg["title"],
      message=alert_msg["message"],
      snapshot=json.dumps(snapshot, ensure_ascii=False),
      started_at=now
    )

    db.session.add(event)
    db.session.commit()
    return event
  except Exception as e:
    db.session.rollback()
    return None

