from ..extensions import db

class Heartbeat(db.Model):
  __tablename__ = "heartbeat"

  machine_id = db.Column(db.Integer, primary_key=True)
  last_seen = db.Column(db.DateTime)