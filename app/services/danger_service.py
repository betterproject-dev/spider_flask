# =========================================
# 위험도 / 작동정지 기준 긴급 메세지 생성 서비스
# =========================================

# 위험 점수 기준(ML 예측 기반 danger_score를 상태로 변환할 때 사용)
EMERGENCY_TH = 70   # 이 이상이면 설비 작동 중지(STOP)
WARNING_TH = 40     # 이 이상이면 경고(WARNING)

# 센서별 임계치(실측 센서값 기준으로 어떤 센서가 "주 원인"인지 고를 때 사용)
TEMP_LIMIT = 45  # 온도
HUM_LIMIT = 40   # 습도
NOISE_LIMIT= 70  # 소음
LEAK_LIMIT= 0    # 누수는 0이면 바로 위험 

def score_to_level(score: float) -> str:
  """
    위험 점수를 기반으로 설비 상태를 판별한다.
    - STOP    : 설비 작동 중지(긴급 알림 대상)
    - WARNING : 주의(시각적 표시/기록용)
    - NORMAL  : 정상
  """
  # 점수가 STOP 기준 이상이면 작동 중지 상태로 판단
  if score >= EMERGENCY_TH:
    return "STOP"
  
  # 점수가 WARNING 기준 이상이면 경고 상태로 판단
  if score >= WARNING_TH:
    return "WARNING"
  
  # 그 외는 정상 상태
  return "NORMAL"

def calc_excess(value, limit):
  """현재값(value)이 기준(limit)을 얼마나 초과했는지(초과량)를 계산한다."""
  # 값이나 기준이 없으면 계산 불가
  if value is None or limit is None:
    return None
  
  # 초과량(현재값 - 기준값)을 소수 2자리로 반환
  return round(value - limit, 2)

def pick_main_sensor(log):
  """
    센서 로그 1건에서 '주 원인' 센서를 선택한다.
    - 온도/습도/소음: (현재값 - 임계치) 초과량이 큰 항목
    - 누수: '진짜 누수일 때만' 후보에 넣고, 매우 큰 가중치로 최우선 처리
  """
  candidates = [] # (센서명, 현재값, 임계치, 초과여부) 후보 리스트

  # 온도/습도/소음: 초과량 기반
  if log.temperature_DS18B20 is not None and log.temperature_DS18B20 >= TEMP_LIMIT:
    candidates.append(("온도센서", log.temperature_DS18B20, TEMP_LIMIT, log.temperature_DS18B20 - TEMP_LIMIT))

  if log.humidity is not None and log.humidity >= HUM_LIMIT:
    candidates.append(("습도센서", log.humidity, HUM_LIMIT, log.humidity - HUM_LIMIT))

  if log.noise is not None and log.noise >= NOISE_LIMIT:
    candidates.append(("소음센서", log.noise, NOISE_LIMIT, log.noise - NOISE_LIMIT))

  # 누수 (DB 기준: 0이면 누수)
  if log.leak is False or log.leak == 0:
    # 누수는 무조건 최우선 (가중치 9999)
    candidates.append(("누수센서", 0, 0, 9999))

  if not candidates:
    return ("UNKNOWN", None, None)
  
  # 초과량(4번째 값) 가장 큰 것 선택
  candidates.sort(key=lambda x: x[3], reverse=True)
  name, value, limit, _ = candidates[0]
  return (name, value, limit)

def make_alert_message(machine_no, sensor_name, value, limit):
  """프론트에서 바로 쓸 수 있도록 알림 제목/메시지 문자열을 생성한다."""

  # 점수 기반(원인 센서 특정 불가) 케이스까지 같이 처리
  if sensor_name in ("센서", "UNKNOWN") or value is None or limit is None:
    return {
      "title": f"{machine_no}호기 긴급(점수 기반) 문제 발생",
      "message": "위험 점수가 기준을 초과했지만, 특정 센서의 임계치 초과는 감지되지 않았습니다."
    }
  
  if sensor_name == "누수센서":
    return {
      "title": f"{machine_no}호기 누수 감지",
      "message": "누수 신호가 감지되어 설비가 즉시 긴급 중지되었습니다."
    }
  # 초과량(현재값 - 기준값) 계산
  excess = calc_excess(value, limit)

  # excess 계산이 안 되는 경우(데이터 타입/None 등) 방어
  if excess is None:
    return {
      "title": f"{machine_no}호기 {sensor_name} 긴급 문제 발생",
      "message": f"센서값: {value}, 허용치: {limit} (초과량 계산 불가)"
    }

  # UI 표시용 title/message 구성(필요하면 포맷만 바꾸면 됨)
  return {
    "title" : f"{machine_no}호기 {sensor_name} 긴급 문제 발생",
    "message" : f"센서값: {value}, 허용치 {limit} 기준 {excess} 초과"
  }