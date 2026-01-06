from sqlalchemy import desc
from datetime import datetime, timedelta
from app import db
import json

from ..models.alert_event import AlertEvent
from ..models.sensors import Sensors
from ..models.heartbeat import Heartbeat
from ..services.danger_service import EMERGENCY_TH, is_leak, is_sensor_over_limit, pick_main_sensor, make_offline_alert_message
from ..services.danger_score_service import load_danger_score

HEARTBEAT_TIMEOUT_SECONDS = 90
SENSORS_RECENT_WINDOW_SECONDS = 180 # 센서 로그가 최근 3분 이내일 때만 "문제 판정"에 사용

def _get_last_score(machine_number: int) -> float | None:
  """
  DangerScore 테이블에서 해당 machine_number의 최신 dangerScore를 가져온다.
  load_danger_score()는 최근 10개를 오래된→최신 순으로 반환하므로 [-1]이 최신.
  """

  scores = load_danger_score(machine_number)
  if not scores:
    return None
  
  last = scores[-1] # 최신
  if not isinstance(last, dict):
    return None
  
  v = last.get("dangerScore")
  if v is None:
    return None
  
  try:
    return float(v)
  except (TypeError, ValueError):
    return None
  
def create_offline_event_if_needed(machine_number: int) -> AlertEvent | None:
  now = datetime.now()

  # heartbeat 게이트( 90초 끊김 아니면 절대 알림 X)
  hb = Heartbeat.query.filter_by(machine_id=machine_number).first()
  if not hb or not hb.last_seen:
    return None
  
  if (now - hb.last_seen) <= timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS):
    return None
  
  #  중복 방지 : 이미 "통신 두절" 이벤트 진행 중이면 스킵
  ongoing = (
    AlertEvent.query
      .filter_by(machine_number=machine_number, level="EMERGENCY")
      .filter(AlertEvent.ended_at.is_(None))
      .filter(AlertEvent.title.like("%통신 두절%"))
      .order_by(desc(AlertEvent.started_at))
      .first()
  )

  if ongoing:
    return None
  
  # 마지막 센서 로그
  last_log = (
    Sensors.query
      .filter_by(machine_number=machine_number)
      .order_by(desc(Sensors.id))
      .first()
  )

  if not last_log or not last_log.created_at:
    return None
  
  # 센서 로그가 너무 오래전이면 "작업 종료" 가능성 높으니 알림 X
  if (now - last_log.created_at) > timedelta(seconds=SENSORS_RECENT_WINDOW_SECONDS):
    return None
  
  # 마지막 위험 점수 (표시 + 문제판정용)
  last_score = _get_last_score(machine_number)
  score_problem = (last_score is not None) and (float(last_score) >= EMERGENCY_TH)

  # 문제 판정
  leak_problem = is_leak(last_log)
  sensor_problem = is_sensor_over_limit(last_log, offline=True) # 오프라인 임계치

  # heartbeat 끊겼어도 ( 누수/센서/점수 ) 문제 없으면 알림 X
  if not (leak_problem or sensor_problem or score_problem):
    return None
  
  # 메시지 생성 ( 오프라인 전용 )
  # - leak 우선
  if leak_problem:
    alert_msg = make_offline_alert_message(
      machine_no=machine_number,
      reason="LEAK",
      danger_score=last_score
    )
  
  # - 센서 문제
  elif sensor_problem:
    sensor_name, value, limit = pick_main_sensor(last_log, offline=True)
    alert_msg = make_offline_alert_message(
      machine_no=machine_number,
      reason="SENSOR",
      sensor_name=sensor_name,
      value=value,
      limit=limit,
      danger_score=last_score
    )
  
  # - 점수 문제
  else:
    alert_msg = make_offline_alert_message(
      machine_no=machine_number,
      reason="SCORE",
      danger_score=last_score
    )

  # snapshot 구성
  snapshot = {
    "heartbeat_last_seen": hb.last_seen.isoformat() if hb.last_seen else None,
    "temperature": last_log.temperature_DS18B20,
    "humidity": last_log.humidity,
    "noise": last_log.noise,
    "leak": last_log.leak,
    "danger_score": float(last_score) if last_score is not None else None,
    "created_at": last_log.created_at.isoformat() if last_log.created_at else None
  }

  # AlertEvent 저장
  try:
    event = AlertEvent(
      machine_number=machine_number,
      level="EMERGENCY",
      danger_score=float(last_score) if last_score is not None else None,
      title=alert_msg["title"],
      message=alert_msg["message"],
      snapshot=json.dumps(snapshot, ensure_ascii=False),
      started_at=now
    )

    db.session.add(event)
    db.session.commit()
    return event
  except Exception:
    db.session.rollback()
    return None


