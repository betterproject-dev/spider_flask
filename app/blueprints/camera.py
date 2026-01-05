from flask import Blueprint, Response
import numpy as np
import cv2
import time
from ultralytics import YOLO
import os
from app.models.defects import Defects
from app.extensions import db
import requests
import threading

bp = Blueprint('camera', __name__)
base_path = os.getcwd()
model_path = os.path.join(base_path, 'app', 'models', 'best.pt')

model = YOLO(model_path)

shared_frame = None
is_object_detected = False # 무게센서가 참고할 변수
saved_object_ids = set() # 이미 DB 저장 완료된 물체 ID 목록 (메모리 관리 필요)

def detection_loop(app):
  global shared_frame, is_object_detected, saved_object_ids
  
  camera = cv2.VideoCapture(0)

  while True:
    success, frame = camera.read()
    if not success:
      time.sleep(0.1)
      continue

    result = model.track(frame, persist=True, conf=0.4, verbose=False)

    current_detected_ids = []
    detected_defects = {} # ID별 불량 정보 저장 {id: set(defects)}

    is_any_real_object = False

    for r in result:
      if r.boxes is not None and r.boxes.id is not None:
        # 감지된 물체들의 ID와 정보를 추출
        boxes = r.boxes.xyxy.cpu().numpy()
        ids = r.boxes.id.cpu().numpy().astype(int)
        clss = r.boxes.cls.cpu().numpy().astype(int)
        masks = r.masks.xy if r.masks is not None else [None] * len(ids)

        for mask, box, obj_id, cls_idx in zip(masks, boxes, ids, clss):
          is_any_real_object = True
          class_name = model.names[cls_idx]
          current_detected_ids.append(obj_id)

          # 화면에 ID와 경계 그리기
          if mask is not None:
            cv2.putText(frame, f"ID:{obj_id} {class_name}", (int(box[0]), int(box[1])-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 255, 0), 2)
          

          # 아직 저장 안 된 새로운 물체라면 불량 분석
          if obj_id not in saved_object_ids:
            if obj_id not in detected_defects:
              detected_defects[obj_id] = {'has_label':False, 'types':set()}

            if class_name == 'Label': detected_defects[obj_id]['has_label'] = True
            elif class_name in ['Crushed', 'Discolored']:
              detected_defects[obj_id]['types'].add(class_name)
            elif class_name == 'Both_Defect':
              detected_defects[obj_id]['types'].update(['Crushed', 'Discolored'])
    
    # 카메라에 물체가 있는지 전역 변수 업데이트(무게 센서용)
    is_object_detected = is_any_real_object

    # 새로운 물체 DB 저장 로직
    if detected_defects:
      with app.app_context():
        for obj_id, info in detected_defects.items():
          # 라벨 검사 추가
          if not info['has_label']:
            info['types'].add('Label')

          target_types = list(info['types']) if info['types'] else ['Normal']

          try:
            for d_type in target_types:
              new_defect = Defects(defect_type=d_type, machine_number=1)
              db.session.add(new_defect)
            db.session.commit()
            requests.get("http://localhost:8888/api/stats/update/1")
            saved_object_ids.add(obj_id) # 저장 완료 목록에 추가
            print(f"[ID:{obj_id}] 저장 완료: {target_types}")
          except Exception as e:
            db.session.rollback()
            print(f"DB 에러: {e}")

    # 너무 오래된 ID 삭제 (메모리 정리 - 최근 100개만 유지)
    if len(saved_object_ids) > 100:
      saved_object_ids = set(list(saved_object_ids)[-50:])
    
    shared_frame = frame.copy()
    time.sleep(0.01)

@bp.record
def start_thread(state):
  thread = threading.Thread(target=detection_loop, args=(state.app,), daemon=True)
  thread.start()


@bp.route('/video_feed')
def video_feed():
  def stream():
    while True:
      if shared_frame is not None:
        ret, buffer = cv2.imencode('.jpg', shared_frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
      time.sleep(0.03)
  # 실시간 비디오 스트림 반환
  return Response(stream(), mimetype='multipart/x-mixed-replace; boundary=frame')
