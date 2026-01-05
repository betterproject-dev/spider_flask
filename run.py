from dotenv import load_dotenv
load_dotenv()
from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == '__main__':
    # use_reloader=False를 추가하여 카메라 중복 점유를 방지합니다.
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False)