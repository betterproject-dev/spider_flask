from ..extensions import db
from datetime import datetime

class Sensors(db.Model):
    __tablename__ = 'sensors'
    
    id = db.Column(db.Integer, primary_key=True)
    machine_number = db.Column(db.Integer, db.ForeignKey('machines.id')) # nullable=False
    created_at = db.Column(db.DateTime, default=datetime.now)
    temperature = db.Column(db.Float) # 온도
    humidity = db.Column(db.Float)  # 습도
    noise = db.Column(db.Float) # 소음
    leak = db.Column(db.Boolean)  # 누수
    
    def to_dict(self):
        return{
            'id':self.id,
            'machine_number':self.machine_number,
            'created_at':self.created_at,
            'temperature':self.temperature,
            'humidity':self.humidity,
            'noise':self.noise,
            'leak':self.leak
        }