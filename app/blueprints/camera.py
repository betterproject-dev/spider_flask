from app import db
from flask import Blueprint, request, jsonify, Response
import numpy as np
import cv2
import time
from ultralytics import YOLO
import os

bp = Blueprint('camera', __name__)
base_path = os.getcwd()
model_path = os.path.join(base_path, 'app', 'models', 'best.pt')

model = YOLO(model_path)

# ---------- 직접 이미지 전송시 필요(postman) ------------
@bp.route('/predict', methods=['POST'])
def predict():
  if 'image' not in request.files:
    return jsonify({'error': 'No image uploaded'}), 400
  
  file = request.files['image']

  # 이미지를 메모리에서 읽기
  img_array = np.frombuffer(file.read(), np.uint8)
  img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

  # 로컬 모델로 추론 실행
  results = model(img, conf=0.4)

  predictions = []

  for r in results:
    # 인스턴스 세그멘테이션 결과 추출
    if r.masks is not None:
      for mask, box in zip(r.masks.xy, r.boxes):
        predictions.append({
          "class":model.names[int(box.cls)],
          "confidence":float(box.conf),
          "points":[{"x":float(x), "y":float(y)} for x, y in mask]
        })

  return jsonify({"predictions":predictions})
#-----------------------------------------------------------


def gen_frames():
  camera = cv2.VideoCapture(0)
  while True:
    success, frame = camera.read()
    if not success:
      break
    else:
      results = model(frame, conf=0.4, verbose=False)

      for r in results:
        # 경계선 그리기
        if r.masks is not None:
          for mask, box in zip(r.masks.xy, r.boxes):
            # 좌표 변환 및 그리기
            pts = np.array(mask, np.int32)
            cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
            # 클래스명 표시
            label = f"{model.names[int(box.cls)]} {float(box.conf):.2f}"
            cv2.putText(frame, label, (int(pts[0][0]), int(pts[0][1])-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

      # 화면 송출용 인코디
      ret, buffer = cv2.imencode('.jpg', frame)
      frame = buffer.tobytes()
      yield (b'--frame\r\n'
             b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
      
      # CPU 과부하 방지 (약 30FPS)
      time.sleep(0.01)
      
@bp.route('/video_feed')
def video_feed():
  # 실시간 비디오 스트림 반환
  return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
