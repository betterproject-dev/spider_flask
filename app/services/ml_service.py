from sqlalchemy import desc
import numpy as np
from ..extensions import model, scaler_X, scaler_y
from ..models.sensors import Sensors

class PredictionService:
  #불러올 칼럼 수
  DATA_COUNT = 10

  #필요한 만큼의 데이터 불러오기
  #return [[온도, 습도, 소음],[온도, 습도, 소음].......]
  @staticmethod
  def get_data(machine_number):
    """최근 10개의 센서 데이터를 가져온다."""
    last_10_logs = Sensors.query.filter_by(machine_number=machine_number).order_by(desc(Sensors.id)).limit(PredictionService.DATA_COUNT).all()
    last_10_logs.reverse()
    log_data = [[log.temperature_DS18B20, log.humidity, log.noise] for log in last_10_logs]
    
    return log_data

  @staticmethod
  def predict_next_values(machine_number):
    """시계열 데이터를 기반으로 다음 센서값을 예측한다."""
    data=PredictionService.get_data(machine_number)
    input_sequence =[]
    
    #첫번째행은 변화율 0
    row = [data[0][0], data[0][1], data[0][2], 0.0, 0.0, 0.0]
    input_sequence.append(row)
    
    #data에 각각 변화율 추가
    for i in range(1,PredictionService.DATA_COUNT):
      curr_data = data[i]
      prev_data = data[i-1]
      
      temp_change_1m = ((curr_data[0]-prev_data[0])/prev_data[0])*100
      hm_change_1m = ((curr_data[1]-prev_data[1])/prev_data[1])*100
      noise_change_1m = ((curr_data[2]-prev_data[2])/prev_data[2])*100
      
      row = [curr_data[0], curr_data[1], curr_data[2], temp_change_1m, hm_change_1m, noise_change_1m]
      input_sequence.append(row)
      
    #스케일링
    scaled_data = scaler_X.transform(input_sequence)
    final_data = np.array([scaled_data])
    
    #예측/역스케일링(복원)
    preded=model.predict(final_data)
    preded_final = scaler_y.inverse_transform(preded)

    # 원래 sensormodel.py에서 쓰던 data도 같이 필요하니까 같이 반환
    return data, preded_final