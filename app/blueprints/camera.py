from flask import Blueprint, request, jsonify, Response, current_app
import numpy as np
import cv2
import time
from ultralytics import YOLO
import os
from app.models.defects import Defects
from app.extensions import db

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


def gen_frames(app):
  camera = cv2.VideoCapture(0)
  last_saved_time = 0 # 마지막 저장 시간 기록
  save_cooldown = 3 # 저장 간격 (2초)

  while True:
    success, frame = camera.read()
    if not success: break

    results = model(frame, conf=0.4, verbose=False)
    current_time = time.time()

    detected_defects = set() # 중복 방지를 위해 set 사용
    has_label = False # 라벨 클래스 존재 여부

    for r in results:
      if r.masks is not None:
        for mask, box in zip(r.masks.xy, r.boxes):
          # 클래스명 가져오기
          class_name = model.names[int(box.cls)]
          # 경계선 그리기
          pts = np.array(mask, np.int32)
          cv2.polylines(frame, [pts], True, (0, 255, 0), 2)
          label = f"{class_name} {float(box.conf):.2f}"
          cv2.putText(frame, label, (int(pts[0][0]), int(pts[0][1])-10),
                      cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
          
          # DB 저장 로직 (불량 클래스일 경우에만 저장)

          # 불량 판별 로직
          if class_name == 'Label':
            has_label = True
          elif class_name == 'Crushed':
            detected_defects.add('Crushed')
          elif class_name == 'Discolored':
            detected_defects.add('Discolored')
          elif class_name == 'Both_Defect':
            detected_defects.add('Crushed')
            detected_defects.add('Discolored')

      # 라벨 없음 판별    
    if not has_label:
      detected_defects.add('Label')
      cv2.putText(frame, "WARNING: MISSING LABEL", (50, 50),
                  cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
      
    # 3. 다중 불량 DB 저장 (리스트에 담긴 모든 불량을 각각 하나씩 저장)
    if detected_defects and (current_time - last_saved_time > save_cooldown):
      with app.app_context():
        try:
          for d_type in detected_defects:
            new_defect = Defects(
              defect_type=d_type,
              machine_number=1
            )
            db.session.add(new_defect)
                    
            db.session.commit() # 리스트 내 모든 불량 동시 커밋
            last_saved_time = current_time
            print(f"✅ DB 저장 완료: {detected_defects}")
        except Exception as e:
            db.session.rollback()
            print(f"❌ DB 저장 에러: {e}")

    # 화면 송출용 인코디
    ret, buffer = cv2.imencode('.jpg', frame)
    frame = buffer.tobytes()
    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
      
    # CPU 과부하 방지 (약 30FPS)
    time.sleep(0.01)
      
@bp.route('/video_feed')
def video_feed():
  # 실시간 비디오 스트림 반환
  return Response(gen_frames(current_app._get_current_object()), mimetype='multipart/x-mixed-replace; boundary=frame')
