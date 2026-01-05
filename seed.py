# seed.py (프로젝트 루트 폴더에 생성)
from app import db, create_app  # your_filename을 실제 app객체가 있는 파일명으로 변경
import random
from app.models.sensors import Sensors

app = create_app()

def insert_dummy():
    with app.app_context():  # 앱 컨텍스트 수동 생성
        # 기존 데이터 삭제 (선택 사항)
        # db.session.query(Sensors).delete()
        
        for _ in range(100):
            temp_ds = round(random.uniform(20.0, 25.0), 2)
            humidity = random.randint(9, 12)
            noise = round(random.uniform(60.0, 65.0), 2)
            leak = random.choice([0, 1])

            sensor = Sensors(
                machine_number=2,
                temperature_DS18B20=temp_ds,
                humidity=humidity,
                noise=noise,
                leak=leak
            )
            db.session.add(sensor)
        
        db.session.commit()
        print("성공적으로 100개의 더미 데이터를 삽입했습니다.")

if __name__ == "__main__":
    insert_dummy()