from app import db
from flask import Blueprint, request, jsonify, Response
import numpy as np
import cv2
import time
from ultralytics import YOLO
from app.extensions import socketio
import os

bp = Blueprint('camera', __name__)
base_path = os.getcwd()
model_path = os.path.join(base_path, 'app', 'models', 'best.pt')

model = YOLO(model_path)

prev_pts = None


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
  # 클래스별 색상 지정 (예시)
  ZONE_RECT = [200, 0, 450, 470]
  
  last_pts_map = {}
  alpha = 0.1
  class_colors = {
      'normal': (0, 255, 0),        # 초록
      'Both_Defect': (0, 0, 255),  # 빨강
      'Label': (255, 0, 0), # 파랑
      'Color_Defect': (0, 255, 255), # 노랑
  }
  while True:
    success, frame = camera.read()
    if not success:
      break
    
    else:
      # 1. 화면에 인식 구역 표시 (선택 사항: 사용자 가이드용)
      cv2.rectangle(frame, (ZONE_RECT[0], ZONE_RECT[1]), (ZONE_RECT[2], ZONE_RECT[3]), (235, 206, 135), 2)
      cv2.putText(frame, "Detection Zone", (ZONE_RECT[0], ZONE_RECT[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 206, 135), 1)
      
      results = model(frame, conf=0.4, verbose=False)
      detected_info = []
      current_pts_map = {}
      
      for idx, r in enumerate(results):
        # 경계선 그리기
        if r.masks is not None:
          for m_idx, (mask, box) in enumerate(zip(r.masks.xy, r.boxes)):
            # --- [추가] 구역 검사 로직 ---
            # 물체 바운딩 박스의 중심점 계산
            b = box.xyxy[0]  # [x1, y1, x2, y2]
            center_x = (b[0] + b[2]) / 2
            center_y = (b[1] + b[3]) / 2

            # 중심점이 ZONE_RECT 안에 있는지 확인
            if (ZONE_RECT[0] <= center_x <= ZONE_RECT[2] and 
                ZONE_RECT[1] <= center_y <= ZONE_RECT[3]):
                
                # 구역 안에 있을 때만 정보 추가 및 그리기 수행
                class_name = model.names[int(box.cls)]
                pts = np.array(mask, np.float32) # 연산을 위해 float32 사용

                # --- [EMA 필터 적용 부분] ---
                # 물체 식별 ID를 간단히 클래스명+인덱스로 지정 (더 정확하려면 추적 알고리즘 필요)
                obj_id = f"{class_name}_{m_idx}"
                
                if obj_id in last_pts_map and last_pts_map[obj_id].shape == pts.shape:
                    # 필터 공식: (현재값 * alpha) + (이전값 * (1 - alpha))
                    pts = (pts * alpha) + (last_pts_map[obj_id] * (1 - alpha))
                
                current_pts_map[obj_id] = pts # 업데이트된 좌표 저장
                display_pts = pts.astype(np.int32) # 화면 출력용 정수 변환
                
                detected_info.append({
                    "class": class_name,
                    "confidence": float(box.conf),
                    "points": display_pts.tolist() # 리스트 변환
                })

                pts = np.array(mask, np.int32)
                color = class_colors.get(class_name, (0, 255, 0))
                cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=2)
                label = f"{class_name} {float(box.conf):.2f}"
                cv2.putText(frame, label, (int(pts[0][0]), int(pts[0][1])-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
      
      # 이전 좌표 갱신
      last_pts_map = current_pts_map

      # 프론트로 실시간전송 socketio
      socketio.emit('yolo_result', detected_info)
      
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
