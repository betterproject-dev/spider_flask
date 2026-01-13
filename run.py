from dotenv import load_dotenv
load_dotenv()
from app import create_app
from app.extensions import socketio
import logging

app = create_app()
log = logging.getLogger('werkzeug')

class PathFilter(logging.Filter):
    def filter(self, record):
        # 로그 메시지에 특정 경로가 포함되어 있으면 False를 반환하여 출력 안 함
        return '/static/uploads/defects/' not in record.getMessage()

# 필터 적용
log.addFilter(PathFilter())

if __name__ == '__main__':
    # use_reloader=False를 추가하여 카메라 중복 점유를 방지합니다.
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False)