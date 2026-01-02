from ..extensions import db
from datetime import datetime

class Defects (db.Model):
  __tablename__ = 'defects'

  id = db.Column(db.Integer, primary_key=True)
  created_at = db.Column(db.DateTime, default=datetime.now)
  defect_type = db.Column(db.Enum('Normal', 'Label', 'Crushed', 'Discolored', 'weight', name='defect_types')) # 불량 종류
  machine_number = db.Column(db.Integer, db.ForeignKey('machines.id'), nullable=False)