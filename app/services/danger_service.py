# =========================================
# 위험도 / 작동정지 기준 긴급 메세지 생성 서비스
# =========================================

# 위험 점수 기준(ML 예측 기반 danger_score를 상태로 변환할 때 사용)
EMERGENCY_TH = 70   # 이 이상이면 설비 작동 중지(STOP)
WARNING_TH = 40     # 이 이상이면 경고(WARNING)

# 센서별 임계치(실측 센서값 기준으로 어떤 센서가 "주 원인"인지 고를 때 사용)
TEMP_LIMIT = 60  # 온도
HUM_LIMIT = 65   # 습도
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
  """센서 로그 1건에서 '긴급 원인'으로 볼 센서(가장 크게 임계치 초과한 항목)를 선택한다."""
  candidates = [] # (센서명, 현재값, 임계치, 초과여부) 후보 리스트

  # 온도 임계치 초과 여부 후보 등록
  candidates.append(("온도센서", log.temperature_DS18B20, TEMP_LIMIT, log.temperature_DS18B20 is not None and log.temperature_DS18B20 >= TEMP_LIMIT))
  # 습도 임계치 초과 여부 후보 등록
  candidates.append(("습도센서", log.humidity, HUM_LIMIT, log.humidity is not None and log.humidity >= HUM_LIMIT))
  # 소음 임계치 초과 여부 후보 등록
  candidates.append(("소음센서", log.noise, NOISE_LIMIT, log.noise is not None and log.noise >= NOISE_LIMIT))
  # 누수는 감지(log.leak가 truthy)되면 초과로 처리(현재값은 0/1 형태로 통일)
  candidates.append(("누수센서", int(bool(log.leak)), LEAK_LIMIT, bool(log.leak)))

  # 임계치를 넘은(초과여부 True) 후보만 추림
  over = [c for c in candidates if c[3]]
  # 어떤 센서도 임계치 초과가 없으면 기본값 반환(점수 기반 STOP 등 케이스 대비)
  if not over:
    # 초과가 없으면 그냥 점수 기반(또는 기본값)
    return ("센서", None, None)
  
  # 초과 정도가 가장 큰 센서를 고르기 위해 (현재값/임계치) 비율로 정렬
  # ※ 누수는 limit=0이라 분모 0이 될 수 있어 x[2] 체크로 방어함
  over.sort(key=lambda x: (x[1] / x[2]) if (x[1] is not None and x[2]) else 0, reverse=True)

  # 가장 위험한(정렬 1등) 센서를 결과로 선택
  name, value, limit, _ = over[0]

  return (name, value, limit)

def make_alert_message(machine_no, sensor_name, value, limit):
  """프론트에서 바로 쓸 수 있도록 알림 제목/메시지 문자열을 생성한다."""
  # 초과량(현재값 - 기준값) 계산
  excess = calc_excess(value, limit)

  # UI 표시용 title/message 구성(필요하면 포맷만 바꾸면 됨)
  return {
    "title" : f"{machine_no}호기 {sensor_name} 긴급 문제 발생",
    "message" : f"센서값: {value}, 허용치 {limit} 기준 {excess} 초과"
  }