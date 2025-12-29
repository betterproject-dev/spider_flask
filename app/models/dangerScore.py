from ..extensions import db

class Machines(db.Model):
    __tablename__ = 'sensormodel'

    id = db.Column(db.Integer, primary_key=True)
    dangerScore = db.Column(db.Integer, nullable = False)
    def to_dict(self):
        return{
            'id':self.id,
            'dangerScore':self.dangerScore
        }
