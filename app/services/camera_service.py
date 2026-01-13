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

    # current_camera_defects는 "감지 여부" (Label=True는 라벨 보임)
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
    # 완료된 물체 큐 (무게센서가 가져감)
    # =========================
    finished_queue = deque(maxlen=300)

    # ID 마지막으로 보인 시각
    active_last_seen = {}

    # 이 시간 동안 안 보이면 ROI 통과 완료 확정
    FINALIZE_GAP_SECONDS = 0.6

    # 진행중 데이터 TTL
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

    @classmethod
    def update_temp_frame(cls, obj_id, frame, box, current_defects):
        """
        ROI 안에 있는 동안:
        - 결함 카운트 누적
        - 가장 좋은 프레임(best_score) 유지
        """
        now = cls._now()
        center_y = (box[1] + box[3]) / 2
        roi_height = cls.ROI_Y2 - cls.ROI_Y1

        with cls._lock:
            if obj_id not in cls.temp_image_buffer:
                cls.temp_image_buffer[obj_id] = {
                    "frame": frame.copy(),
                    "stats": {"total": 0, "label_count": 0, "crushed_count": 0, "discolored_count": 0},
                    "best_score": 0,
                    "first_seen": now,
                    "last_seen": now,
                }

            data = cls.temp_image_buffer[obj_id]
            data["last_seen"] = now

            stats = data["stats"]
            stats["total"] += 1

            if current_defects.get("Label"): stats["label_count"] += 1
            if current_defects.get("Crushed"): stats["crushed_count"] += 1
            if current_defects.get("Discolored"): stats["discolored_count"] += 1

            center_x = (box[0] + box[2]) / 2
            roi_w = cls.ROI_X2 - cls.ROI_X1
            roi_h = cls.ROI_Y2 - cls.ROI_Y1

            dx = abs(center_x - (roi_w / 2))
            dy = abs(center_y - (roi_h / 2))

            score = 1 / (dx * 2.0 + dy * 1.0 + 1)
            
            if score > data["best_score"]:
                data["frame"] = frame.copy()
                data["best_score"] = score

            cls._trim_temp_buffer()

    @classmethod
    def _finalize_object(cls, obj_id):
        """
        ROI에서 사라진 obj_id를 "완료"로 확정해서 finished_queue에 넣는다.
        """
        with cls._lock:
            data = cls.temp_image_buffer.pop(obj_id, None)

        if not data:
            return

        frame = data.get("frame")
        stats = data.get("stats", {})
        total = stats.get("total", 0)

        # ✅ (중요) 너무 적게 찍힌 건 버림 (배경/오탐 방지)
        if frame is None or total < 3:
            return

        label_ratio = (stats.get("label_count", 0) / total) if total else 0.0

        # ✅ Label 불량: 라벨이 일정 비율 이하로만 보이면 불량(True)
        LABEL_RATIO_TH = 0.3
        label_defect = (label_ratio < LABEL_RATIO_TH)

        # ✅ Crushed/Discolored: 한 번이라도 잡히면 불량(True)
        crushed_defect = stats.get("crushed_count", 0) > 0
        discolored_defect = stats.get("discolored_count", 0) > 0

        final_defects = {
            "Label": label_defect,
            "Crushed": crushed_defect,
            "Discolored": discolored_defect
        }

        # ✅ (중요) finished_queue에 넣어야 무게센서가 get_current_frame()으로 꺼냄
        with cls._lock:
            cls.finished_queue.append({
                "ts": cls._now(),
                "frame": frame,
                "defects": final_defects
            })

        logger.info(
            f"✅ FINALIZED obj_id={obj_id} total={total} "
            f"label_ratio={label_ratio:.2f} stats={stats} defects={final_defects}"
        )

    @classmethod
    def get_current_frame(cls):
        """
        무게센서가 호출:
        - finished_queue에서 가장 최근 완료된 물체를 꺼내 반환
        """
        with cls._lock:
            if not cls.finished_queue:
                return None, None
            item = cls.finished_queue.pop()
            return item["frame"], item["defects"]

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

            # ROI 좌표 -> 원본(frame) 좌표로 변환
            x1 = int(box[0] + cls.ROI_X1)
            y1 = int(box[1] + cls.ROI_Y1)
            x2 = int(box[2] + cls.ROI_X1)
            y2 = int(box[3] + cls.ROI_Y1)

            # 결함이면 빨강, 정상/라벨이면 초록
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

            # ROI 가이드
            cv2.rectangle(frame, (cls.ROI_X1, cls.ROI_Y1), (cls.ROI_X2, cls.ROI_Y2), (0, 255, 255), 2)
            cv2.putText(frame, "DETECTION ZONE", (cls.ROI_X1, cls.ROI_Y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            if cls.frame_skip_count % 2 == 0:
                roi_img = raw_frame[cls.ROI_Y1:cls.ROI_Y2, cls.ROI_X1:cls.ROI_X2]
                results = cls.model.track(roi_img, persist=True, conf=0.4, verbose=False)

                current_boxes = []
                detected_info_for_socket = []

                if results[0].boxes.id is not None:
                    cls.last_detection_time = cls._now()
                    boxes = results[0].boxes.xyxy.cpu().numpy()
                    ids = results[0].boxes.id.cpu().numpy().astype(int)
                    clss = results[0].boxes.cls.cpu().numpy().astype(int)

                    frame_defects = {"Label": False, "Crushed": False, "Discolored": False}

                    for box, obj_id, cls_idx in zip(boxes, ids, clss):
                        obj_id = int(obj_id)

                        # 마지막 seen time 기록
                        cls.active_last_seen[obj_id] = cls._now()

                        class_name = cls.model.names[cls_idx]
                        id_defects = {"Label": False, "Crushed": False, "Discolored": False}

                        if class_name in ("Label", "Normal"):
                            id_defects["Label"] = True
                        elif class_name == "Crushed":
                            id_defects["Crushed"] = True
                        elif class_name == "Discolored":
                            id_defects["Discolored"] = True
                        elif class_name == "Both_Defect":
                            id_defects["Crushed"] = True
                            id_defects["Discolored"] = True

                        # 누적 업데이트
                        cls.update_temp_frame(obj_id, raw_frame, box, id_defects)

                        frame_defects["Label"] |= id_defects["Label"]
                        frame_defects["Crushed"] |= id_defects["Crushed"]
                        frame_defects["Discolored"] |= id_defects["Discolored"]

                        detected_info_for_socket.append({"id": obj_id, "class": class_name})
                        current_boxes.append({"box": box, "id": obj_id, "class": class_name})

                    # 프레임 단위로 1번만 갱신/전송
                    cls.current_camera_defects = frame_defects
                    socketio.emit("yolo_result", detected_info_for_socket)
                    cls.last_detected_boxes = current_boxes

                else:
                    socketio.emit("yolo_result", [])

                # ✅ 핵심: 감지 유무와 상관없이 "사라진 ID"는 finalize 해야 finished_queue가 채워짐
                now = cls._now()
                to_finalize = [oid for oid, last_seen in list(cls.active_last_seen.items())
                               if (now - last_seen) > cls.FINALIZE_GAP_SECONDS]

                for oid in to_finalize:
                    cls.active_last_seen.pop(oid, None)
                    cls._finalize_object(oid)

                # 박스 표시 (분석 프레임에서도 표시)
                if cls.last_detected_boxes:
                    cls._draw_boxes(frame, cls.last_detected_boxes)

                cls.is_object_detected = (results[0].boxes.id is not None) or (cls._now() - cls.last_detection_time < 1.0)
                if not cls.is_object_detected:
                    cv2.putText(frame, "STATUS: OBJECT NOT FOUND", (cls.ROI_X1, cls.ROI_Y1 + 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            else:
                # 분석 안 하는 프레임에서도 마지막 박스 유지(깜빡임 방지)
                if cls.last_detected_boxes:
                    cls._draw_boxes(frame, cls.last_detected_boxes)

            # 최종 프레임 공유(모니터링용)
            cls.shared_frame = frame.copy()
            socketio.sleep(0.001)
