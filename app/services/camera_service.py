import os
import time
import cv2
import threading
import logging
import collections
from collections import deque
from ultralytics import YOLO
from app.extensions import socketio

logger = logging.getLogger(__name__)

class CameraService:
    # =========================
    # 전역 상태
    # =========================
    shared_frame = None
    last_detection_time = 0
    frame_skip_count = 0
    is_object_detected = False

    current_camera_defects = {
        "Label": False,
        "Crushed": False,
        "Discolored": False
    }

    last_detected_boxes = []

    # =========================
    # 모델 로드
    # =========================
    base_path = os.getcwd()
    model_path = os.path.join(base_path, "app", "models", "best.pt")
    model = YOLO(model_path)

    # =========================
    # ROI
    # =========================
    ROI_X1, ROI_Y1 = 150, 30
    ROI_X2, ROI_Y2 = 490, 470

    # =========================
    # 진행중 누적 버퍼
    # =========================
    temp_image_buffer = collections.OrderedDict()
    MAX_BUFFER_SIZE = 200

    # =========================
    # 완료된 물체 큐 + 중복 방지
    # =========================
    finished_queue = deque(maxlen=300)
    _finalized_ids = set()
    _finalized_lock = threading.Lock()

    # ID 마지막으로 보인 시각
    active_last_seen = {}

    FINALIZE_GAP_SECONDS = 0.6
    BUFFER_TTL_SECONDS = 20.0

    _lock = threading.Lock()

    @classmethod
    def _now(cls):
        return time.time()

    @classmethod
    def _trim_temp_buffer(cls):
        """진행중 버퍼 정리(크기+TTL)"""
        while len(cls.temp_image_buffer) > cls.MAX_BUFFER_SIZE:
            cls.temp_image_buffer.popitem(last=False)

        now = cls._now()
        to_delete = []
        for obj_id, data in cls.temp_image_buffer.items():
            last_seen = data.get("last_seen", 0)
            if last_seen and (now - last_seen) > cls.BUFFER_TTL_SECONDS:
                to_delete.append(obj_id)

        for obj_id in to_delete:
            cls.temp_image_buffer.pop(obj_id, None)
            cls.active_last_seen.pop(obj_id, None)
            
        # finalized_ids도 주기적으로 정리
        with cls._finalized_lock:
            if len(cls._finalized_ids) > 100:
                ids_to_remove = list(cls._finalized_ids)[:50]
                for oid in ids_to_remove:
                    cls._finalized_ids.discard(oid)

        with cls._lock:
            while cls.finished_queue:
                oldest = cls.finished_queue[0]
                age = now - oldest.get("ts", 0)
                if age > 15.0:
                    removed = cls.finished_queue.popleft()
                    logger.warning(
                        f"[CLEANUP_OLD] obj_id={removed.get('obj_id')}"
                        f"age={age:.1f}s -> 오래된 데이터, 제거"
                    )
                else:
                    break

    @classmethod
    def update_temp_frame(cls, obj_id, frame, box, current_defects):
        now = cls._now()
        roi_w = cls.ROI_X2 - cls.ROI_X1
        center_x = (box[0] + box[2]) / 2

        with cls._lock:
            if obj_id not in cls.temp_image_buffer:
                cls.temp_image_buffer[obj_id] = {
                    "frame": frame.copy(), 
                    "captured_defects": {"Label": False, "Crushed": False, "Discolored": False},
                    "defect_counts": {"Label": 0, "Crushed": 0, "Discolored": 0}, # ⭐ 카운트 추가
                    "best_score": -1.0, 
                    "last_seen": now, 
                    "passed_center": False
                }

            data = cls.temp_image_buffer[obj_id]
            data["last_seen"] = now

            # 바로 True로 만들지 않고 카운트를 올립니다.
            for defect_type in ["Label", "Crushed", "Discolored"]:
                if current_defects.get(defect_type, False):
                    data["defect_counts"][defect_type] += 1
                
                # 최소 20프레임 이상 검출되었을 때만 최종 결함으로 확정 (수치 조정 가능)
                if data["defect_counts"][defect_type] >= 20:
                    data["captured_defects"][defect_type] = True

            # 중앙 부근 베스트 샷 저장
            score = 1 / (abs(center_x - roi_w * 0.5) + 1)
            if score > data["best_score"]:
                data["frame"] = frame.copy()
                data["best_score"] = score

            if center_x > roi_w * 0.5:
                data["passed_center"] = True

    @classmethod
    def _finalize_object(cls, obj_id):
        with cls._finalized_lock:
            if obj_id in cls._finalized_ids:
                return
            cls._finalized_ids.add(obj_id)
        
        with cls._lock:
            data = cls.temp_image_buffer.pop(obj_id, None)

        if not data or data.get("frame") is None:
            return
        
        current_ts = cls._now()
        final_defects = data.get("captured_defects", {"Label": False, "Crushed": False, "Discolored": False})

        with cls._lock:
            # ⭐ 핵심 로직: 0.5초 이내에 이미 처리된 다른 ID가 있는지 확인
            merged = False
            for item in reversed(cls.finished_queue):
                # 마지막 아이템과 시간 차이가 0.5초 이내라면? (시간은 환경에 맞게 조정 가능)
                if current_ts - item["ts"] < 0.5: 
                    # 이전 데이터에 현재 발견된 결함들을 합침 (OR 연산)
                    item["defects"]["Label"] |= final_defects["Label"]
                    item["defects"]["Crushed"] |= final_defects["Crushed"]
                    item["defects"]["Discolored"] |= final_defects["Discolored"]
                    
                    logger.info(f"[MERGED] ID:{obj_id} data merged into previous ID:{item['obj_id']}")
                    merged = True
                    break
            
            # 겹치는 시간이 없으면 새로 추가
            if not merged:
                cls.finished_queue.append({
                    "ts": current_ts,
                    "obj_id": obj_id,
                    "frame": data["frame"],
                    "defects": final_defects
                })
                logger.info(f"[FINALIZED] ID:{obj_id} | Label:{final_defects['Label']} | Crushed:{final_defects['Crushed']} | Discolored:{final_defects['Discolored']}")

    @classmethod
    def get_realtime_defect_status(cls):
        with cls._lock:
            # is_label_ok: 라벨이 감지되면 True (정상)
            is_label_ok = cls.current_camera_defects.get("Label", False)
            is_crushed = cls.current_camera_defects.get("Crushed", False)
            is_discolored = cls.current_camera_defects.get("Discolored", False)
            
            # 표의 마지막 행: 아무것도 감지되지 않은 경우 (Normal - 아무것도 없음)
            is_nothing = not (is_label_ok or is_crushed or is_discolored)

            # status 반환 (DefectService와 일치시키기 위해 원본값 위주로 반환)
            return {
                "Label": is_label_ok,
                "Crushed": is_crushed,
                "Discolored": is_discolored,
                "is_nothing": is_nothing
            }


    @classmethod
    def get_current_frame(cls):
        """
        ⭐ DEPRECATED: timestamp 없는 구버전
        하위 호환성을 위해 유지
        """
        with cls._lock:
            if not cls.finished_queue:
                return None, None
            
            item = cls.finished_queue.pop()
            logger.info(f"[POP_QUEUE] obj_id={item.get('obj_id')} ts={item.get('ts'):.2f}")
            return item["frame"], item["defects"]

    @classmethod
    def get_current_frame_with_timestamp(cls):
        """
        ⭐ 새로운 API: timestamp도 함께 반환
        무게센서가 호출: finished_queue에서 가장 최근 완료된 물체를 꺼내 반환
        
        Returns:
            tuple: (frame, defects, timestamp) or (None, None, 0)
        """
        with cls._lock:
            if not cls.finished_queue:
                return None, None, 0
            
            item = cls.finished_queue.pop()
            logger.info(
                f"[POP_QUEUE] obj_id={item.get('obj_id')} "
                f"ts={item.get('ts'):.2f} "
                f"age={cls._now() - item.get('ts'):.2f}s"
            )
            return item["frame"], item["defects"], item["ts"]
    
    @classmethod
    def get_finished_queue_size(cls):
        with cls._lock:
            return len(cls.finished_queue)

    @classmethod
    def reset_camera_defects(cls):
        cls.current_camera_defects = {"Label": False, "Crushed": False, "Discolored": False}

    @classmethod
    def _draw_boxes(cls, frame, boxes_to_draw):
        """화면에 박스 그리기"""
        for item in boxes_to_draw:
            box = item["box"]
            class_name = item.get("class", "")
            obj_id = item.get("id", "")

            x1 = int(box[0] + cls.ROI_X1)
            y1 = int(box[1] + cls.ROI_Y1)
            x2 = int(box[2] + cls.ROI_X1)
            y2 = int(box[3] + cls.ROI_Y1)

            is_defect = class_name in ("Crushed", "Discolored", "Both_Defect")
            color = (0, 0, 255) if is_defect else (0, 255, 0)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"ID:{obj_id} {class_name}",
                (x1, max(0, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2
            )

    @classmethod
    def detection_loop(cls, app):
        camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        time.sleep(2.0)
        if not camera.isOpened():
            logger.error("❌ 카메라를 열 수 없습니다.")
            return

        logger.info("🚀 실시간 감지 서비스 시작")

        while True:
            success, frame = camera.read()
            if not success:
                socketio.sleep(0.01)
                continue

            raw_frame = frame.copy()
            cls.frame_skip_count += 1

            # ROI 가이드라인
            cv2.rectangle(frame, (cls.ROI_X1, cls.ROI_Y1), (cls.ROI_X2, cls.ROI_Y2), (0, 255, 255), 2)

            if cls.frame_skip_count % 2 == 0:
                roi_img = raw_frame[cls.ROI_Y1:cls.ROI_Y2, cls.ROI_X1:cls.ROI_X2]
                results = cls.model.track(roi_img, persist=True, conf=0.5, iou=0.5, tracker="bytetrack.yaml",verbose=False)

                if results[0].boxes is not None and results[0].boxes.id is not None:
                    boxes = results[0].boxes.xyxy.cpu().numpy()
                    ids = results[0].boxes.id.cpu().numpy().astype(int)
                    clss = results[0].boxes.cls.cpu().numpy().astype(int)

                    current_boxes = []
                    frame_defects = {"Label": False, "Crushed": False, "Discolored": False}
                    combined_obj_data = {}

                    for box, obj_id, cls_idx in zip(boxes, ids, clss):
                        obj_id = int(obj_id)
                        cls.active_last_seen[obj_id] = cls._now()
                        class_name = cls.model.names[cls_idx]
                        if obj_id not in combined_obj_data:
                            combined_obj_data[obj_id] = {
                            "box": box, 
                            "defects": {"Label": False, "Crushed": False, "Discolored": False}
                        }

                        if class_name == "Label":
                            combined_obj_data[obj_id]["defects"]["Label"] = True
                        elif class_name == "Crushed":
                            combined_obj_data[obj_id]["defects"]["Crushed"] = True
                        elif class_name == "Discolored":
                            combined_obj_data[obj_id]["defects"]["Discolored"] = True
                        elif class_name == "Both_Defect":
                            combined_obj_data[obj_id]["defects"]["Crushed"] = True
                            combined_obj_data[obj_id]["defects"]["Discolored"] = True

                        current_boxes.append({"box": box, "id": obj_id, "class": class_name})

                        # 2. 이미지 저장 순간(best_score)을 위해 데이터 업데이트
                        # 이 함수 내부에서 이미 같은 obj_id에 대해 정보를 합치도록 되어있어야 함
                    for obj_id, info in combined_obj_data.items():
                        cls.active_last_seen[obj_id] = cls._now()
                        # 여기서 info["defects"]["Label"]은 진짜 Label 박스가 있을 때만 True입니다.
                        cls.update_temp_frame(obj_id, raw_frame, info["box"], info["defects"])
                        
                        # 3. UI 표시용 프레임 결함 합치기
                        frame_defects["Label"] |= info["defects"]["Label"]
                        frame_defects["Crushed"] |= info["defects"]["Crushed"]
                        frame_defects["Discolored"] |= info["defects"]["Discolored"]
                        
                        current_boxes.append({"box": box, "id": obj_id, "class": class_name})

                    cls.current_camera_defects = frame_defects
                    cls.last_detected_boxes = current_boxes
                    cls.last_detection_time = cls._now()
                    cls.is_object_detected = True
                    socketio.emit("yolo_result", [{"id": b["id"], "class": b["class"]} for b in current_boxes])

                else:
                    cls.last_detected_boxes = []
                    cls.current_camera_defects = {"Label": False, "Crushed": False, "Discolored": False}
                    cls.is_object_detected = False
                    socketio.emit("yolo_result", [])

                # 사라진 물체 Finalize
                now = cls._now()
                to_fin = [
                    oid for oid, d in cls.temp_image_buffer.items()
                    if (now - d.get("last_seen", 0)) > cls.FINALIZE_GAP_SECONDS
                    and d.get("passed_center", False)
                ]
                for oid in to_fin:
                    cls.active_last_seen.pop(oid, None)
                    cls._finalize_object(oid)

            # 화면 그리기
            if cls.is_object_detected and cls.last_detected_boxes:
                cls._draw_boxes(frame, cls.last_detected_boxes)
            else:
                cv2.putText(frame, "STATUS: OBJECT NOT FOUND", (cls.ROI_X1, cls.ROI_Y1 + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            cls.shared_frame = frame.copy()
            socketio.sleep(0.001)