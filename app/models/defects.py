from ..extensions import db
from datetime import datetime

class Defects (db.Model):
  __tablename__ = 'defects'

  id = db.Column(db.Integer, primary_key=True)
  created_at = db.Column(db.DateTime, default=datetime.now)
  Label = db.Column(db.Boolean, default=False)
  Crushed = db.Column(db.Boolean, default=False)
  Discolored = db.Column(db.Boolean, default=False)
  weight = db.Column(db.Boolean, default=False)
  is_Defect = db.Column(db.Boolean, default=False)
  image_url = db.Column(db.String(255), nullable=True)
  machine_number = db.Column(db.Integer, db.ForeignKey('machines.id'), nullable=False)