import os
import time
import cv2
import threading
import requests
from flask import Blueprint, Response
from ultralytics import YOLO
from app.extensions import socketio, db
from app.models.defects import Defects

bp = Blueprint('camera', __name__)

# [모델 로드]
base_path = os.getcwd()
model_path = os.path.join(base_path, 'app', 'models', 'best.pt')
model = YOLO(model_path)

# [전역 변수 설정]
shared_frame = None
saved_object_ids = set()
frame_skip_count = 0
is_object_detected = False
last_detected_boxes = []  # 이전 프레임의 박스 정보를 저장 (깜빡임 방지)

# [감지 영역(ROI) 설정] 640x480 해상도 기준 중앙 영역
ROI_X1, ROI_Y1 = 150, 20
ROI_X2, ROI_Y2 = 490, 460

def background_task(app, detected_defects):
    """DB 저장 및 외부 API 호출을 처리하는 비동기 워커"""
    with app.app_context():
        for obj_id, info in detected_defects.items():
            if not info['has_label']:
                info['types'].add('Label')
            
            target_types = list(info['types']) if info['types'] else ['Normal']
            try:
                for d_type in target_types:
                    new_defect = Defects(defect_type=d_type, machine_number=1)
                    db.session.add(new_defect)
                db.session.commit()
                
                # 통계 서버 업데이트 요청 (8888 포트)
                try:
                    requests.get("http://localhost:8888/api/stats/update/1", timeout=0.5)
                except:
                    pass
                print(f"✅ [ID:{obj_id}] 비동기 작업 완료")
            except Exception as e:
                db.session.rollback()
                print(f"❌ DB 에러: {e}")

def detection_loop(app):
    global shared_frame, saved_object_ids, frame_skip_count, is_object_detected, last_detected_boxes
    
    # 카메라 설정
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1) # 지연 방지용 버퍼 최소화

    time.sleep(2.0)
    if not camera.isOpened():
        print("❌ 카메라를 열 수 없습니다.")
        return

    print("🚀 실시간 감지 루프 시작")

    while True:
        success, frame = camera.read()
        if not success:
            socketio.sleep(0.01)
            continue

        # 1. 배경 가이드 라인 (감지 영역) 그리기
        cv2.rectangle(frame, (ROI_X1, ROI_Y1), (ROI_X2, ROI_Y2), (0, 255, 255), 2)
        cv2.putText(frame, "DETECTION ZONE", (ROI_X1, ROI_Y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        frame_skip_count += 1
        
        # 2. YOLO 분석 루프 (2프레임당 1번 실행하여 부하 감소)
        if frame_skip_count % 2 == 0:
            roi_img = frame[ROI_Y1:ROI_Y2, ROI_X1:ROI_X2] # 영역 잘라내기
            results = model.track(roi_img, persist=True, conf=0.4, verbose=False)

            current_boxes = []
            detected_info_for_socket = []
            detected_defects = {}
            temp_is_detected = False

            if results[0].boxes.id is not None:
                temp_is_detected = True
                boxes = results[0].boxes.xyxy.cpu().numpy()
                ids = results[0].boxes.id.cpu().numpy().astype(int)
                clss = results[0].boxes.cls.cpu().numpy().astype(int)
                confs = results[0].boxes.conf.cpu().numpy()

                for box, obj_id, cls_idx, conf in zip(boxes, ids, clss, confs):
                    class_name = model.names[cls_idx]
                    
                    # 그리기용 정보 저장
                    current_boxes.append({"box": box, "id": obj_id, "class": class_name})

                    # 소켓 전송용 데이터 구성
                    detected_info_for_socket.append({
                        "id": int(obj_id), 
                        "class": class_name, 
                        "confidence": float(conf)
                    })

                    # 새로운 객체인 경우 비동기 저장 스케줄링
                    if obj_id not in saved_object_ids:
                        if obj_id not in detected_defects:
                            detected_defects[obj_id] = {'has_label': False, 'types': set()}
                        
                        if class_name == 'Label': detected_defects[obj_id]['has_label'] = True
                        elif class_name in ['Crushed', 'Discolored']: detected_defects[obj_id]['types'].add(class_name)
                        elif class_name == 'Both_Defect': detected_defects[obj_id]['types'].update(['Crushed', 'Discolored'])
                        
                        saved_object_ids.add(obj_id)

                # 소켓으로 프론트엔드에 실시간 데이터 전송
                socketio.emit('yolo_result', detected_info_for_socket)
            
            # 전역 변수 업데이트
            last_detected_boxes = current_boxes
            is_object_detected = temp_is_detected
            
            # 비동기 작업 스레드 실행
            if detected_defects:
                threading.Thread(target=background_task, args=(app, detected_defects), daemon=True).start()

        # 3. 매 프레임마다 박스 그리기 (분석하지 않는 프레임에서도 last_detected_boxes 사용)
        for item in last_detected_boxes:
            box = item['box']
            # ROI 좌표를 원본 이미지 좌표로 변환
            x1, y1 = int(box[0] + ROI_X1), int(box[1] + ROI_Y1)
            x2, y2 = int(box[2] + ROI_X1), int(box[3] + ROI_Y1)
            
            # 상태에 따른 색상 (정상: 녹색, 결함: 빨간색)
            color = (0, 255, 0) if item['class'] == 'Label' or item['class'] == 'Normal' else (0, 0, 255)
            
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"ID:{item['id']} {item['class']}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # 메모리 정리 (오래된 ID 삭제)
        if len(saved_object_ids) > 100:
            saved_object_ids = set(list(saved_object_ids)[-50:])

        # 최종 프레임 공유 및 대기
        shared_frame = frame.copy()
        socketio.sleep(0.001)

@bp.record
def start_thread(state):
    thread = threading.Thread(target=detection_loop, args=(state.app,), daemon=True)
    thread.start()

@bp.route('/video_feed')
def video_feed():
    def stream():
        while True:
            if shared_frame is not None:
                # JPEG 인코딩 (품질 80으로 속도 최적화)
                ret, buffer = cv2.imencode('.jpg', shared_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            socketio.sleep(0.03) # 약 30FPS 전송
    return Response(stream(), mimetype='multipart/x-mixed-replace; boundary=frame')