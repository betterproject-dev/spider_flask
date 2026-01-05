from ..extensions import db

class DangerScore(db.Model):
    __tablename__ = 'danger_score'

    id = db.Column(db.Integer, primary_key=True)
    dangerScore = db.Column(db.Float, nullable = False)
    machine_number = db.Column(db.Integer, db.ForeignKey('machines.id'), nullable=False)
    def to_dict(self):
        return{
            'id':self.id,
            'dangerScore':self.dangerScore,
            'machine_number':self.machine_number
        }
