import cv2
import mediapipe as mp
import subprocess
import numpy as np
import threading
import time
import serial

from flask import Flask, Response, jsonify


# =========================================================
# Flask 初始化
# =========================================================

app = Flask(__name__)


# =========================================================
# Arduino 序列連線設定
# =========================================================

ARDUINO_PORT = "/dev/ttyUSB0"
ARDUINO_BAUD_RATE = 9600

arduino = None
serial_lock = threading.Lock()


def connect_arduino():
    """
    建立 Raspberry Pi 與 Arduino 的序列連線。
    """

    global arduino

    try:
        arduino = serial.Serial(
            port=ARDUINO_PORT,
            baudrate=ARDUINO_BAUD_RATE,
            timeout=1,
            write_timeout=1
        )

        # Arduino 開啟 Serial 後通常會重新啟動
        time.sleep(2)

        arduino.reset_input_buffer()
        arduino.reset_output_buffer()

        print(f"成功連線至 Arduino：{ARDUINO_PORT}")

    except serial.SerialException as error:
        arduino = None

        print(
            f"警告：Arduino 連線失敗：{error}"
        )


# 啟動時先嘗試連 Arduino
connect_arduino()


# =========================================================
# MediaPipe Hands 初始化
# =========================================================

mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

hands = mp_hands.Hands(
    static_image_mode=False,

    # 同時辨識兩隻手
    max_num_hands=2,

    model_complexity=0,

    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)


# =========================================================
# 相機影像狀態
# =========================================================

latest_camera_frame = None
latest_output_frame = None

camera_frame_lock = threading.Lock()
output_frame_lock = threading.Lock()


# =========================================================
# 系統狀態 Lock
# =========================================================

state_lock = threading.Lock()


# =========================================================
# 左右手辨識結果
#
# Right = 角色 1
# Left  = 角色 2
# =========================================================

right_hand_finger_count = None
left_hand_finger_count = None

right_hand_action = "NOT_DETECTED"
left_hand_action = "NOT_DETECTED"


# =========================================================
# 角色命令
# =========================================================

# 角色 1：右手
right_character_command = "IDLE"

# 角色 2：左手
left_character_command = "IDLE"


# =========================================================
# 手勢穩定判定
# =========================================================

# 連續辨識幾次相同手勢才確認
STABLE_FRAMES_REQUIRED = 5

# 同一隻手兩次不同動作之間的冷卻時間
COMMAND_COOLDOWN_SECONDS = 1.0


# =========================================================
# 左右手各自獨立的辨識狀態
# =========================================================

hand_states = {

    "Right": {
        "candidate": -1,
        "frames": 0,
        "last_sent": -1,
        "last_command_time": 0.0
    },

    "Left": {
        "candidate": -1,
        "frames": 0,
        "last_sent": -1,
        "last_command_time": 0.0
    }
}


# =========================================================
# 動作名稱
# =========================================================

ACTION_NAMES = {

    0: "READY",

    1: "WAVE",

    2: "SALUTE",

    3: "DOUBLE_STRIKE",

    4: "SWORD_SWING",

    5: "OPEN_HAND"
}


# =========================================================
# 傳送 Arduino 指令
# =========================================================

def send_arduino_command(command):
    """
    傳送：
        R1
        R2
        ...
        L1
        L2
        ...

    Arduino 端使用換行作為一筆指令結尾。
    """

    global arduino

    # 即使 Arduino 沒連，也把預計命令印出來
    print(f"準備傳送 Arduino：{command}")

    if arduino is None or not arduino.is_open:

        print(
            f"Arduino 未連線，測試命令：{command}"
        )

        return False

    message = f"{command}\n"

    try:

        with serial_lock:

            arduino.write(
                message.encode("utf-8")
            )

            arduino.flush()

        print(
            f"Arduino 已收到：{command}"
        )

        return True

    except (
        serial.SerialException,
        serial.SerialTimeoutException
    ) as error:

        print(
            f"Arduino 指令傳送失敗：{error}"
        )

        return False


# =========================================================
# Raspberry Pi Camera 執行緒
# =========================================================

def camera_thread():

    global latest_camera_frame

    command = [

        "rpicam-vid",

        "-t", "0",

        "--inline",

        "--codec", "mjpeg",

        "--nopreview",

        "--width", "1280",

        "--height", "720",

        "--framerate", "60",

        "-o", "-"
    ]

    try:

        process = subprocess.Popen(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.DEVNULL,

            bufsize=0
        )

    except FileNotFoundError:

        print(
            "錯誤：找不到 rpicam-vid"
        )

        return

    byte_buffer = b""

    while True:

        if process.stdout is None:

            time.sleep(0.1)

            continue

        chunk = process.stdout.read(
            16 * 1024
        )

        if not chunk:

            print(
                "警告：相機串流中斷"
            )

            time.sleep(0.1)

            continue

        byte_buffer += chunk

        # JPEG 起點
        start_index = byte_buffer.find(
            b"\xff\xd8"
        )

        if start_index == -1:

            if len(byte_buffer) > 4 * 1024 * 1024:
                byte_buffer = b""

            continue

        # JPEG 終點
        end_index = byte_buffer.find(
            b"\xff\xd9",
            start_index + 2
        )

        if end_index == -1:

            if len(byte_buffer) > 4 * 1024 * 1024:

                byte_buffer = (
                    byte_buffer[start_index:]
                )

            continue

        jpg_data = (
            byte_buffer[
                start_index:end_index + 2
            ]
        )

        byte_buffer = (
            byte_buffer[
                end_index + 2:
            ]
        )

        image_array = np.frombuffer(
            jpg_data,
            dtype=np.uint8
        )

        frame = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR
        )

        if frame is not None:

            with camera_frame_lock:

                latest_camera_frame = frame


# =========================================================
# 計算伸直手指數
# =========================================================

def count_fingers(hand_landmarks):

    landmarks = hand_landmarks.landmark

    count = 0

    # 食指
    if landmarks[8].y < landmarks[6].y:
        count += 1

    # 中指
    if landmarks[12].y < landmarks[10].y:
        count += 1

    # 無名指
    if landmarks[16].y < landmarks[14].y:
        count += 1

    # 小指
    if landmarks[20].y < landmarks[18].y:
        count += 1

    # 大拇指
    thumb_tip_distance = np.hypot(

        landmarks[4].x
        - landmarks[17].x,

        landmarks[4].y
        - landmarks[17].y
    )

    thumb_joint_distance = np.hypot(

        landmarks[3].x
        - landmarks[17].x,

        landmarks[3].y
        - landmarks[17].y
    )

    if (
        thumb_tip_distance
        > thumb_joint_distance
    ):
        count += 1

    return count


# =========================================================
# 手指數 → 動作名稱
# =========================================================

def get_hand_action_name(finger_count):

    return ACTION_NAMES.get(
        finger_count,
        "UNKNOWN"
    )


# =========================================================
# 重設某一隻手
# =========================================================

def reset_hand_state(hand_label):

    state = hand_states[hand_label]

    state["candidate"] = -1
    state["frames"] = 0
    state["last_sent"] = -1

    # last_command_time 不一定要清
    # 但手離開後重新出現，希望能立即控制
    state["last_command_time"] = 0.0


# =========================================================
# 分析單一左右手
#
# Right → CHARACTER_1 → R1 ~ R4
# Left  → CHARACTER_2 → L1 ~ L4
# =========================================================

def analyze_hand_gesture(
    hand_label,
    finger_count
):

    global right_character_command
    global left_character_command

    state = hand_states[hand_label]

    current_time = time.monotonic()

    # =====================================================
    # 現階段只有 1～4 根手指是真正控制動作
    #
    # 0 = READY
    # 5 = OPEN_HAND
    #
    # 暫時只顯示，不傳 Arduino
    # =====================================================

    if finger_count not in (1, 2, 3, 4):

        state["candidate"] = -1
        state["frames"] = 0

        # 進到非控制手勢後，
        # 下次同一動作可以再次觸發
        state["last_sent"] = -1

        return

    # =====================================================
    # 手勢改變
    # =====================================================

    if finger_count != state["candidate"]:

        state["candidate"] = finger_count

        state["frames"] = 1

    else:

        state["frames"] += 1


    # =====================================================
    # 還沒有穩定到指定幀數
    # =====================================================

    if (
        state["frames"]
        < STABLE_FRAMES_REQUIRED
    ):

        return


    # =====================================================
    # 同一個動作保持時，不重複一直傳
    # =====================================================

    if (
        finger_count
        == state["last_sent"]
    ):

        return


    # =====================================================
    # 冷卻時間
    # =====================================================

    if (
        current_time
        - state["last_command_time"]
        < COMMAND_COOLDOWN_SECONDS
    ):

        return


    # =====================================================
    # 右手 = 角色 1
    # =====================================================

    if hand_label == "Right":

        character_name = "CHARACTER_1"

        command = (
            f"R{finger_count}"
        )

        with state_lock:
            right_character_command = command


    # =====================================================
    # 左手 = 角色 2
    # =====================================================

    else:

        character_name = "CHARACTER_2"

        command = (
            f"L{finger_count}"
        )

        with state_lock:
            left_character_command = command


    action_name = (
        get_hand_action_name(
            finger_count
        )
    )


    # =====================================================
    # Terminal 顯示
    # =====================================================

    print(
        "======================================"
    )

    print(
        f"{character_name}"
    )

    print(
        f"Hand: {hand_label}"
    )

    print(
        f"Fingers: {finger_count}"
    )

    print(
        f"Action: {action_name}"
    )

    print(
        f"Command: {command}"
    )

    print(
        "======================================"
    )


    # =====================================================
    # 傳給 Arduino
    # =====================================================

    send_arduino_command(
        command
    )


    # 即使 Arduino 現在沒接，
    # 也更新防重複狀態，
    # 避免 Terminal 每幀狂刷。
    state["last_sent"] = finger_count

    state["last_command_time"] = (
        time.monotonic()
    )


# =========================================================
# MediaPipe 影像辨識執行緒
# =========================================================

def vision_thread():

    global latest_output_frame

    global right_hand_finger_count
    global left_hand_finger_count

    global right_hand_action
    global left_hand_action

    global right_character_command
    global left_character_command


    frame_count = 0

    fps_start_time = time.time()

    fps = 0.0


    while True:

        # =================================================
        # 取得最新 Pi Camera 畫面
        # =================================================

        with camera_frame_lock:

            frame = (

                latest_camera_frame.copy()

                if latest_camera_frame
                is not None

                else None
            )

        if frame is None:

            time.sleep(0.01)

            continue


        # =================================================
        # 鏡像畫面
        # =================================================

        frame = cv2.flip(
            frame,
            1
        )

        frame_count += 1


        # =================================================
        # FPS
        # =================================================

        if frame_count % 10 == 0:

            current_time = time.time()

            elapsed_time = (
                current_time
                - fps_start_time
            )

            if elapsed_time > 0:

                fps = round(
                    10 / elapsed_time,
                    1
                )

            fps_start_time = (
                current_time
            )


        # =================================================
        # 每兩幀做一次 MediaPipe
        # =================================================

        if frame_count % 2 == 0:

            image_rgb = cv2.cvtColor(

                frame,

                cv2.COLOR_BGR2RGB
            )

            results = hands.process(
                image_rgb
            )


            # =============================================
            # 用來記錄這一幀有看到哪些手
            # =============================================

            seen_hands = set()


            # =============================================
            # 有偵測到手
            # =============================================

            if results.multi_hand_landmarks:

                for (
                    hand_landmarks,
                    handedness

                ) in zip(

                    results.multi_hand_landmarks,
                    results.multi_handedness
                ):

                    # =====================================
                    # MediaPipe 原始 Left / Right
                    # =====================================

                    hand_label = (

                        handedness
                        .classification[0]
                        .label
                    )




                    seen_hands.add(
                        hand_label
                    )


                    # =====================================
                    # 畫手部骨架
                    # =====================================

                    mp_draw.draw_landmarks(

                        frame,

                        hand_landmarks,

                        mp_hands.HAND_CONNECTIONS
                    )


                    # =====================================
                    # 計算手指數
                    # =====================================

                    finger_count = (
                        count_fingers(
                            hand_landmarks
                        )
                    )


                    # =====================================
                    # 動作名稱
                    # =====================================

                    action_name = (
                        get_hand_action_name(
                            finger_count
                        )
                    )


                    # =====================================
                    # 儲存辨識結果
                    # =====================================

                    with state_lock:

                        if hand_label == "Right":

                            right_hand_finger_count = (
                                finger_count
                            )

                            right_hand_action = (
                                action_name
                            )

                        elif hand_label == "Left":

                            left_hand_finger_count = (
                                finger_count
                            )

                            left_hand_action = (
                                action_name
                            )


                    # =====================================
                    # 分析這一隻手的控制命令
                    # =====================================

                    analyze_hand_gesture(

                        hand_label,

                        finger_count
                    )


                    # =====================================
                    # 手腕附近顯示資訊
                    # =====================================

                    frame_height, frame_width = (
                        frame.shape[:2]
                    )

                    wrist = (
                        hand_landmarks
                        .landmark[0]
                    )

                    text_x = int(
                        wrist.x
                        * frame_width
                    )

                    text_y = int(
                        wrist.y
                        * frame_height
                    ) - 20


                    # =====================================
                    # Right 顯示角色 1
                    # Left 顯示角色 2
                    # =====================================

                    if hand_label == "Right":

                        character_text = "P1"

                    else:

                        character_text = "P2"


                    cv2.putText(

                        frame,

                        (
                            f"{character_text} "
                            f"{hand_label}: "
                            f"{finger_count} / "
                            f"{action_name}"
                        ),

                        (
                            text_x,
                            text_y
                        ),

                        cv2.FONT_HERSHEY_SIMPLEX,

                        0.65,

                        (
                            0,
                            255,
                            255
                        ),

                        2
                    )


            # =============================================
            # 本幀沒有偵測到右手
            # =============================================

            if "Right" not in seen_hands:

                with state_lock:

                    right_hand_finger_count = None

                    right_hand_action = (
                        "NOT_DETECTED"
                    )

                    right_character_command = (
                        "IDLE"
                    )

                reset_hand_state(
                    "Right"
                )


            # =============================================
            # 本幀沒有偵測到左手
            # =============================================

            if "Left" not in seen_hands:

                with state_lock:

                    left_hand_finger_count = None

                    left_hand_action = (
                        "NOT_DETECTED"
                    )

                    left_character_command = (
                        "IDLE"
                    )

                reset_hand_state(
                    "Left"
                )


        # =================================================
        # 取得目前狀態
        # =================================================

        with state_lock:

            right_fingers = (
                right_hand_finger_count
            )

            left_fingers = (
                left_hand_finger_count
            )

            right_action = (
                right_hand_action
            )

            left_action = (
                left_hand_action
            )

            right_cmd = (
                right_character_command
            )

            left_cmd = (
                left_character_command
            )


        # =================================================
        # 顯示文字
        # =================================================

        right_text = (

            right_fingers

            if right_fingers is not None

            else "-"
        )


        left_text = (

            left_fingers

            if left_fingers is not None

            else "-"
        )


        # =================================================
        # FPS
        # =================================================

        cv2.putText(

            frame,

            f"FPS: {fps}",

            (10, 30),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.8,

            (
                0,
                255,
                0
            ),

            2
        )


        # =================================================
        # 角色 1：右手
        # =================================================

        cv2.putText(

            frame,

            (
                f"P1 Right: "
                f"{right_text} / "
                f"{right_action}"
            ),

            (10, 70),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.65,

            (
                255,
                255,
                0
            ),

            2
        )


        # =================================================
        # 角色 2：左手
        # =================================================

        cv2.putText(

            frame,

            (
                f"P2 Left: "
                f"{left_text} / "
                f"{left_action}"
            ),

            (10, 105),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.65,

            (
                255,
                255,
                0
            ),

            2
        )


        # =================================================
        # 角色 1 指令
        # =================================================

        cv2.putText(

            frame,

            f"P1 CMD: {right_cmd}",

            (10, 140),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.65,

            (
                0,
                0,
                255
            ),

            2
        )


        # =================================================
        # 角色 2 指令
        # =================================================

        cv2.putText(

            frame,

            f"P2 CMD: {left_cmd}",

            (10, 175),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.65,

            (
                255,
                0,
                255
            ),

            2
        )


        # =================================================
        # JPEG 編碼
        # =================================================

        encode_success, encoded_frame = (
            cv2.imencode(

                ".jpg",

                frame,

                [
                    int(
                        cv2.IMWRITE_JPEG_QUALITY
                    ),
                    60
                ]
            )
        )


        if encode_success:

            with output_frame_lock:

                latest_output_frame = (
                    encoded_frame.tobytes()
                )


# =========================================================
# Flask MJPEG 串流
# =========================================================

def generate_frames():

    while True:

        with output_frame_lock:

            frame_bytes = (
                latest_output_frame
            )

        if frame_bytes is None:

            time.sleep(0.01)

            continue

        yield (

            b"--frame\r\n"

            b"Content-Type: image/jpeg\r\n\r\n"

            + frame_bytes

            + b"\r\n"
        )

        time.sleep(0.01)


# =========================================================
# Flask 首頁
# =========================================================

@app.route("/video_feed")
def video_feed():

    return Response(

        generate_frames(),

        mimetype=(
            "multipart/x-mixed-replace; "
            "boundary=frame"
        )
    )


# =========================================================
# 狀態 API
# =========================================================

@app.route("/get_command")
def get_command():

    with state_lock:

        response_data = {

            # =============================================
            # 角色 1
            # =============================================

            "character_1": {

                "hand":
                    "Right",

                "finger_count":
                    right_hand_finger_count,

                "action":
                    right_hand_action,

                "command":
                    right_character_command
            },


            # =============================================
            # 角色 2
            # =============================================

            "character_2": {

                "hand":
                    "Left",

                "finger_count":
                    left_hand_finger_count,

                "action":
                    left_hand_action,

                "command":
                    left_character_command
            },


            # =============================================
            # Arduino
            # =============================================

            "arduino_connected": (

                arduino is not None

                and arduino.is_open
            )
        }

    return jsonify(
        response_data
    )


# =========================================================
# 啟動
# =========================================================

if __name__ == "__main__":

    threading.Thread(

        target=camera_thread,

        daemon=True
    ).start()


    threading.Thread(

        target=vision_thread,

        daemon=True
    ).start()


    app.run(

        host="0.0.0.0",

        port=5000,

        threaded=True,

        debug=False,

        use_reloader=False
    )