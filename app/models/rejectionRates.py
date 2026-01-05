from ..extensions import db
from datetime import datetime

class RejectionRates (db.Model):
  __tablename__ = 'rejection_rates'

  id = db.Column(db.Integer, primary_key=True)
  created_at = db.Column(db.DateTime, default=datetime.now)
  rejection_rate = db.Column(db.Double) # 불량률
  total_inspected = db.Column(db.Integer) # 총 검사 개수
  total_rejected = db.Column(db.Integer) # 총 불량 개수
  machine_number = db.Column(db.Integer, db.ForeignKey('machines.id'), nullable=False)