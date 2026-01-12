from sqlalchemy import desc
from datetime import datetime, timedelta
from app import db
import json
from sqlalchemy.exc import IntegrityError

from ..models.alert_event import AlertEvent
from ..models.sensors import Sensors
from ..models.heartbeat import Heartbeat
from .danger_service import DangerService
from .danger_score_service import DangerScoreService

class AlertEventService:
  HEARTBEAT_TIMEOUT = 90
  RECENT_WINDOW = 180 # 센서 로그가 최근 3분 이내일 때만 "문제 판정"에 사용

  @staticmethod
  def _active_key_for(machine_number: int) -> str:
    return f"EMERGENCY:{machine_number}"
  
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
  def _append_reason_to_event_snapshot(event: AlertEvent, reason_code: str, payload: dict | None = None) -> AlertEvent | None:
    """
    - JSON 컬럼(dict) / 문자열(JSON) 둘 다 안전하게 처리
    - reasons 배열 유지
    - danger_score는 최대값 유지
    - payload의 None은 덮어쓰지 않음
    """
    try:
      snap = {}

      if event.snapshot:
        # JSON 컬럼이면 dict일 수 있음
        if isinstance(event.snapshot, dict):
          snap = dict(event.snapshot)
        elif isinstance(event.snapshot, str):
          try:
            snap = json.loads(event.snapshot)
          except Exception:
            snap = {}
        else:
          snap = {}

      reasons = snap.get("reasons", [])
      if not isinstance(reasons, list):
        reasons = [str(reasons)]

      if reason_code not in reasons:
        reasons.append(reason_code)
      snap["reasons"] = reasons

      if payload:
        for k, v in payload.items():
          if v is None:
            continue

          if k == "danger_score":
            old = snap.get("danger_score")
            if isinstance(old, (int, float)) and isinstance(v, (int, float)):
              snap["danger_score"] = max(old, v)
            else:
              snap["danger_score"] = v
          else:
            snap[k] = v

      # JSON 컬럼이면 dict 그대로 넣어도 됨
      event.snapshot = snap
      db.session.add(event)
      db.session.commit()
      return event

    except Exception:
      db.session.rollback()
      return None
  
  @staticmethod
  def create_realtime_event_if_needed(machine_number: int, last_log, danger_score: float) -> AlertEvent | None:
    """
    [실시간 긴급 이벤트 생성/누적]

    생성 조건
    1) 누수 발생
    2) 위험 점수(EMERGENCY_TH=70) 이상

    정책(오프라인과 통일)
    - 동일 machine_number에 진행중(ended_at=None) EMERGENCY가 있으면
      새 이벤트 생성 대신 해당 이벤트 snapshot에 원인(reasons)을 누적한다.
    - 신규 생성 시에도 snapshot에 reasons를 넣어 구조를 통일한다.
    """
    now = datetime.now()

    leak_problem = DangerService.is_leak(last_log)
    score_problem = danger_score >= DangerService.EMERGENCY_TH

    if not (leak_problem or score_problem):
      return None

    # reason 결정 (누수 우선)
    reason_code = "REALTIME_LEAK" if leak_problem else "REALTIME_SCORE"
    active_key = AlertEventService._active_key_for(machine_number)

    # 1) 진행중 EMERGENCY가 있으면 snapshot에 reason 누적 후 반환
    ongoing = (
      AlertEvent.query
        .filter(AlertEvent.active_key == active_key)
        .filter(AlertEvent.ended_at.is_(None))
        .order_by(desc(AlertEvent.started_at))
        .first()
    )
    if ongoing:
      payload = {
        "realtime_updated_at": now.isoformat(),
        "danger_score": float(danger_score),
        "last_sensor_created_at": last_log.created_at.isoformat() if getattr(last_log, "created_at", None) else None
      }
      return AlertEventService._append_reason_to_event_snapshot(ongoing, reason_code, payload)

    # 2) 메시지 생성 (누수 우선)
    if leak_problem:
      alert_msg = DangerService.make_alert_message(machine_number, "누수센서", 0, 0)
    else:
      sensor_name, value, limit = DangerService.pick_main_sensor(last_log)
      alert_msg = DangerService.make_alert_message(machine_number, sensor_name, value, limit)

    # 3) 신규 생성 시 snapshot에도 reasons 포함(통일)
    snapshot = {
      "reasons": [reason_code],
      "realtime_created_at": now.isoformat(),
      "temperature": getattr(last_log, "temperature_DS18B20", None),
      "humidity": getattr(last_log, "humidity", None),
      "noise": getattr(last_log, "noise", None),
      "leak": getattr(last_log, "leak", None),
      "danger_score": float(danger_score),
      "created_at": last_log.created_at.isoformat() if getattr(last_log, "created_at", None) else None
    }

    event = AlertEvent(
      machine_number=machine_number,
      level="EMERGENCY",
      danger_score=float(danger_score),
      title=alert_msg["title"],
      message=alert_msg["message"],
      snapshot=snapshot,
      started_at=now,
      ended_at=None,
      active_key=active_key
    )
    
    try:
      db.session.add(event)
      db.session.commit()
      return event
    except IntegrityError:
      # 동시에 다른 스레드가 먼저 생성했음 → 그 이벤트에 누적
      db.session.rollback()
      ongoing2 = (
        AlertEvent.query
          .filter(AlertEvent.active_key == active_key)
          .filter(AlertEvent.ended_at.is_(None))
          .order_by(desc(AlertEvent.started_at))
          .first()
      )
      if not ongoing2:
        return None

      payload = {
        "realtime_updated_at": now.isoformat(),
        "danger_score": float(danger_score),
        "last_sensor_created_at": last_log.created_at.isoformat() if getattr(last_log, "created_at", None) else None
      }
      return AlertEventService._append_reason_to_event_snapshot(ongoing2, reason_code, payload)
    except Exception:
      db.session.rollback()
      return None

  @staticmethod
  def create_offline_event_if_needed(machine_number: int) -> AlertEvent | None:
    """
    [오프라인(통신 두절) 긴급 이벤트 생성]
    생성 조건
      - heartbeat가 HEARTBEAT_TIMEOUT(기본 90초) 이상 끊겼고
      - 마지막 센서 로그가 RECENT_WINDOW(기본 180초) 이내이며
      - 누수(leak) 또는 오프라인 임계치 초과 센서가 있을 때만 EMERGENCY 이벤트 생성
      (danger_score는 메시지/스냅샷 참고용으로만 첨부)
    """
    
    now = datetime.now()

    # heartbeat 게이트( 90초 끊김 아니면 절대 알림 X)
    hb = Heartbeat.query.filter_by(machine_id=machine_number).first()
    if not hb or not hb.last_seen:
      return None
    
    offline_seconds = (now - hb.last_seen).total_seconds()

    if offline_seconds <= AlertEventService.HEARTBEAT_TIMEOUT:
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

    if (now - last_log.created_at) > timedelta(seconds=AlertEventService.RECENT_WINDOW):
      return None
    
    # 문제 판정
    leak_problem = DangerService.is_leak(last_log)
    sensor_problem = DangerService.is_sensor_over_limit(last_log, offline=True) # 오프라인 임계치

    # heartbeat 끊겼어도 ( 누수/센서/점수 ) 문제 없으면 알림 X
    if not (leak_problem or sensor_problem):
      return None
    
    # 마지막 위험 점수 (표시 + 문제판정용)
    last_score = AlertEventService._get_last_score(machine_number)
    reason_code = "OFFLINE_LEAK" if leak_problem else "OFFLINE_SENSOR"
    active_key = AlertEventService._active_key_for(machine_number)
    
    
    # 진행중 있으면 누적
    ongoing = (
      AlertEvent.query
        .filter(AlertEvent.active_key == active_key)
        .filter(AlertEvent.ended_at.is_(None))
        .order_by(desc(AlertEvent.started_at))
        .first()
    )
    if ongoing:
      payload = {
        "offline_updated_at": now.isoformat(),
        "heartbeat_last_seen": hb.last_seen.isoformat(),
        "offline_seconds": float(offline_seconds),
        "danger_score": float(last_score) if last_score is not None else None,
        "last_sensor_created_at": last_log.created_at.isoformat()
      }
      return AlertEventService._append_reason_to_event_snapshot(ongoing, reason_code, payload)

    # 메시지 생성
    if leak_problem:
      alert_msg = DangerService.make_offline_alert_message(
        machine_no=machine_number,
        reason="LEAK",
        danger_score=last_score,
        offline_seconds=offline_seconds,
        heartbeat_timeout=AlertEventService.HEARTBEAT_TIMEOUT
      )
    else:
      sensor_name, value, limit = DangerService.pick_main_sensor(last_log, offline=True)
      alert_msg = DangerService.make_offline_alert_message(
        machine_no=machine_number,
        reason="SENSOR",
        sensor_name=sensor_name,
        value=value,
        limit=limit,
        danger_score=last_score,
        offline_seconds=offline_seconds,
        heartbeat_timeout=AlertEventService.HEARTBEAT_TIMEOUT
      )

    snapshot = {
      "reasons": [reason_code],
      "heartbeat_last_seen": hb.last_seen.isoformat(),
      "offline_seconds": float(offline_seconds),
      "offline_updated_at": now.isoformat(),
      "temperature": last_log.temperature_DS18B20,
      "humidity": last_log.humidity,
      "noise": last_log.noise,
      "leak": last_log.leak,
      "danger_score": float(last_score) if last_score is not None else None,
      "created_at": last_log.created_at.isoformat()
    }

    event = AlertEvent(
      machine_number=machine_number,
      level="EMERGENCY",
      danger_score=float(last_score) if last_score is not None else None,
      title=alert_msg["title"],
      message=alert_msg["message"],
      snapshot=snapshot,
      started_at=now,
      ended_at=None,
      active_key=active_key
    )

    try:
      db.session.add(event)
      db.session.commit()
      return event

    except IntegrityError:
      # 여기 없으면 offline도 2개 생김
      db.session.rollback()
      ongoing2 = (
        AlertEvent.query
          .filter(AlertEvent.active_key == active_key)
          .filter(AlertEvent.ended_at.is_(None))
          .order_by(desc(AlertEvent.started_at))
          .first()
      )
      if not ongoing2:
        return None

      payload = {
        "offline_updated_at": now.isoformat(),
        "heartbeat_last_seen": hb.last_seen.isoformat(),
        "offline_seconds": float(offline_seconds),
        "danger_score": float(last_score) if last_score is not None else None,
        "last_sensor_created_at": last_log.created_at.isoformat()
      }
      return AlertEventService._append_reason_to_event_snapshot(ongoing2, reason_code, payload)

    except Exception:
      db.session.rollback()
      return None

