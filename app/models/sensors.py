from ..extensions import db
from datetime import datetime

class Sensors(db.Model):
    __tablename__ = 'sensors'
    
    id = db.Column(db.Integer, primary_key=True)
    machine_number = db.Column(db.Integer, db.ForeignKey('machines.id')) # nullable=False
    created_at = db.Column(db.DateTime, default=datetime.now)
    temperature_DS18B20 = db.Column(db.Float) # 온도(부착형)
    temperature = db.Column(db.Float) # 온도
    humidity = db.Column(db.Float)  # 습도
    noise = db.Column(db.Float) # 소음
    leak = db.Column(db.Boolean)  # 누수
    