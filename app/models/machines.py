from ..extensions import db

class Machines(db.Model):
    __tablename__ = 'machines'

    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(10), nullable=False)
    sensors = db.relationship('Sensors', backref=db.backref('machine'))
