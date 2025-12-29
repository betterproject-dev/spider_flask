import os
import secrets

class Config:
  # 공통 Config

  # 로그인/세션 안 써도 Flask 내부 기능(확장/보안 토큰 등) 때문에 두는 게 안전함
  SECRET_KEY = secrets.token_urlsafe(32)

  # DB (Azure/로컬 공통)
  SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI")
  SQLALCHEMY_TRACK_MODIFICATIONS = False

  # 개발 중 SQL 로그 보고 싶으면 True, 배포에서는 False 권장
  SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true"

  # 한글 JSON 깨짐 방지
  JSON_AS_ASCII = False

  # MQTT
  MQTT_BROKER = "soyeon"
  MQTT_PORT = 1883

  # CORS (프론트 주소)
  CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173"
  ).split(",") if o.strip()]

# 개발용 Config
class DevelopConfig(Config):
  DEBUG = True # DEBUG = Flask 전체 디버그 모드
  SQLALCHEMY_ECHO = True # 개발에서 쿼리 로그 보고 싶으면 True

# 배포용 Config
class ProductConfig(Config):
  DEBUG = False
  SQLALCHEMY_ECHO = False # 배포에서느 보통 False 권장

config = {
  'develop' : DevelopConfig,
  'product' : ProductConfig
}





