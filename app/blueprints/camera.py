import cv2
import threading
from flask import Blueprint, Response
from app.extensions import socketio
from app.services.camera_service import CameraService

bp = Blueprint('camera', __name__)

@bp.record
def start_thread(state):
    thread = threading.Thread(target=CameraService.detection_loop, args=(state.app,), daemon=True)
    thread.start()

@bp.route('/video_feed')
def video_feed():
    def stream():
        timeout = 0
        while CameraService.shared_frame is None and timeout < 50:
            socketio.sleep(0.1)
            timeout += 1

        while True:
            frame = CameraService.shared_frame
            if frame is not None:
                # JPEG 인코딩 (품질 80으로 속도 최적화)
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            socketio.sleep(0.03) # 약 30FPS 전송
    return Response(stream(), mimetype='multipart/x-mixed-replace; boundary=frame')