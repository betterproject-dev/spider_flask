from datetime import datetime
from ..extensions import db
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.mysql import JSON

AlertLevel = SAEnum("NORMAL", "WARNING", "EMERGENCY", name="alert_level")

class AlertEvent(db.Model):
  __tablename__ = "alert_events"

  id = db.Column(db.Integer, primary_key=True, autoincrement=True)

  machine_number = db.Column(db.Integer, db.ForeignKey('machines.id'), index=True) # nullable=False

  # 관계 연결 (이걸 해두면 event.machine.location 이런 게 가능)
  machine = db.relationship("Machines", backref=db.backref("alert_events", lazy=True))

  level = db.Column(AlertLevel, nullable=False, default="WARNING", index=True)
  danger_score = db.Column(db.Float, nullable=True)

  title = db.Column(db.String(100), nullable=False, default="긴급 알림")
  message = db.Column(db.String(255), nullable=False)

  # 긴급 시점 센서값 스냅샷 저장 (온도/습도/소음/누수/created_at 등)
  snapshot = db.Column(JSON, nullable=True)

  started_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
  ended_at = db.Column(db.DateTime, nullable=True, index=True) # 정상복귀/관리자 조치 시
  acknowledged_at = db.Column(db.DateTime, nullable=True, index=True) # 모달 '확인' 누른 시점

  # 진행중 EMERGENCY 1개 강제용 키
  active_key = db.Column(db.String(64), nullable=True, unique=True, index=True)

  def to_dict(self):
    return {
      "id" : self.id,
      "machine_number" : self.machine_number,
      "machine_location": self.machine.location if self.machine else None,
      "level" : self.level,
      "danger_score" : self.danger_score,
      "title" : self.title,
      "message" : self.message,
      "snapshot" : self.snapshot,
      "started_at" : self.started_at,
      "ended_at" : self.ended_at,
      "acknowledged_at" : self.acknowledged_at,
      "active_key" : self.active_key
    }