from sqlalchemy import desc
from datetime import datetime, timedelta
from app import db
import json

from ..models.alert_event import AlertEvent
from ..models.sensors import Sensors
from ..models.heartbeat import Heartbeat
from .danger_service import DangerService
from .danger_score_service import DangerScoreService

class AlertEventService:
  HEARTBEAT_TIMEOUT = 90
  RECENT_WINDOW = 180 # 센서 로그가 최근 3분 이내일 때만 "문제 판정"에 사용

  @staticmethod
  def _get_last_score(machine_number: int) -> float | None:
    """
    DangerScore 테이블에서 해당 machine_number의 최신 dangerScore를 가져온다.
    load_danger_score()는 최근 10개를 오래된→최신 순으로 반환하므로 [-1]이 최신.
    """

    scores = DangerScoreService.load_danger_score(machine_number)
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
  
  @staticmethod
  def create_offline_event_if_needed(machine_number: int) -> AlertEvent | None:
    """
    [오프라인(통신 두절) 긴급 이벤트 생성]
    특정 설비(machine_number)에 대해 Heartbeat가 일정 시간(HEARTBEAT_TIMEOUT_SECONDS) 이상 끊겼고,
    동시에 "문제 징후"가 확인될 때만 AlertEvent(EMERGENCY)를 생성한다.

    생성 조건(게이트)
    1) Heartbeat.last_seen 존재
    2) (now - last_seen) > HEARTBEAT_TIMEOUT_SECONDS
    3) 중복 방지: '통신 두절' 제목의 EMERGENCY 진행중(ended_at=None) 이벤트가 없어야 함
    4) 마지막 센서 로그(last_log)가 존재하고, created_at이 최근 SENSORS_RECENT_WINDOW_SECONDS 이내여야 함
      - 센서 로그가 너무 오래되면(작업 종료/전원 종료 가능성) 오탐 방지를 위해 이벤트 생성하지 않음
    5) Heartbeat가 끊겼더라도 아래 중 하나라도 "문제"로 판단되어야 함
      - leak_problem: 누수 감지 (is_leak)
      - sensor_problem: 오프라인용 센서 임계치 초과 (is_sensor_over_limit(..., offline=True))
      - score_problem: 마지막 dangerScore가 EMERGENCY_TH 이상

    메시지 생성 우선순위
    - LEAK 문제 > SENSOR 문제 > SCORE 문제
    (오프라인 상황에서도 가장 위험한 원인을 우선 표시)

    저장 내용
    - AlertEvent(level="EMERGENCY", title/message, danger_score, started_at)
    - snapshot: heartbeat 마지막 시각 + 마지막 센서 값 + danger_score + 센서 로그 시각을 JSON으로 저장

    Returns:
      AlertEvent | None
      - 조건 충족 및 DB 저장 성공 시: 생성된 AlertEvent 반환
      - 조건 미충족 또는 저장 실패 시: None 반환 (실패 시 rollback)
    """
    now = datetime.now()

    # heartbeat 게이트( 90초 끊김 아니면 절대 알림 X)
    hb = Heartbeat.query.filter_by(machine_id=machine_number).first()
    if not hb or not hb.last_seen or (now - hb.last_seen) <= timedelta(seconds=AlertEventService.HEARTBEAT_TIMEOUT):
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
    if not last_log or (now - last_log.created_at) > timedelta(seconds=AlertEventService.RECENT_WINDOW):
      return None
    
    # 마지막 위험 점수 (표시 + 문제판정용)
    last_score = AlertEventService._get_last_score(machine_number)
    score_problem = (last_score is not None) and (float(last_score) >= DangerService.EMERGENCY_TH)

    # 문제 판정
    leak_problem = DangerService.is_leak(last_log)
    sensor_problem = DangerService.is_sensor_over_limit(last_log, offline=True) # 오프라인 임계치

    # heartbeat 끊겼어도 ( 누수/센서/점수 ) 문제 없으면 알림 X
    if not (leak_problem or sensor_problem or score_problem):
      return None
    
    # 메시지 생성 ( 오프라인 전용 )
    # - leak 우선
    if leak_problem:
      alert_msg = DangerService.make_offline_alert_message(
        machine_no=machine_number,
        reason="LEAK",
        danger_score=last_score
      )
    
    # - 센서 문제
    elif sensor_problem:
      sensor_name, value, limit = DangerService.pick_main_sensor(last_log, offline=True)
      alert_msg = DangerService.make_offline_alert_message(
        machine_no=machine_number,
        reason="SENSOR",
        sensor_name=sensor_name,
        value=value,
        limit=limit,
        danger_score=last_score
      )
    
    # - 점수 문제
    else:
      alert_msg = DangerService.make_offline_alert_message(
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


