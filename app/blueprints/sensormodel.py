from app import db
from flask import Blueprint

bp = Blueprint('sensormodel', __name__)

#불러올 칼럼 수
DATA_COUNT = 10

#필요한 만큼의 데이터 불러오기
#return [[온도, 습도, 소음],[온도, 습도, 소음].......]
def get_data(machine_number):
  global DATA_COUNT
  return

#예측데이터 받아오기  
@bp.get('/predict/<machine_number>')
def predictData(machine_number):
  data=get_data(machine_number)