import cv2
import mediapipe as mp
import subprocess
import atexit
import signal
import numpy as np
import threading
import time
import serial
from flask import Flask, Response, jsonify, render_template, request
app = Flask(__name__)
# Arduino serial settings
ARDUINO_PORT = '/dev/ttyUSB0'
ARDUINO_BAUD_RATE = 9600
# 測試模式：未接 Arduino 也能推進劇本；正式演出改 False
SIMULATION_MODE = False
# 影像鏡像：若辨識左右手相反，切換 True/False 再測試
VIDEO_MIRROR = False
arduino = None
serial_lock = threading.Lock()
def connect_arduino():
    global arduino
    try:
        arduino = serial.Serial(port=ARDUINO_PORT, baudrate=ARDUINO_BAUD_RATE,
                                timeout=1, write_timeout=1)
        time.sleep(2)  # Arduino reset after serial port is opened
        arduino.reset_input_buffer()
        arduino.reset_output_buffer()
        print(f'成功連線至 Arduino：{ARDUINO_PORT}')
    except (serial.SerialException, OSError) as error:
        arduino = None
        print(f'警告：Arduino 連線失敗：{error}')
if not SIMULATION_MODE:
    connect_arduino()
else:
    print('SIMULATION_MODE=True：不連線 Arduino，僅模擬動作指令')
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils
hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2,
                       model_complexity=0, min_detection_confidence=0.7,
                       min_tracking_confidence=0.7)
latest_camera_frame = None
camera_frame_id = 0
latest_output_frame = None
# 獨立預覽影格與辨識結果，避免 MJPEG 被 hands.process() 卡住
latest_output_seq = 0
latest_visual_hands = []
latest_visual_time = 0.0
latest_ai_fps = 0.0
visual_lock = threading.Lock()
PREVIEW_FPS_LIMIT = 20
PREVIEW_JPEG_QUALITY = 60

camera_frame_lock = threading.Lock()
output_frame_lock = threading.Lock()
puppet_frame = None
puppet_frame_time = None
puppet_frame_lock = threading.Lock()
state_lock = threading.Lock()
right_hand_finger_count = None
left_hand_finger_count = None
right_hand_action = 'NOT_DETECTED'
left_hand_action = 'NOT_DETECTED'
right_character_command = 'IDLE'
left_character_command = 'IDLE'
STABLE_FRAMES_REQUIRED = 5
COMMAND_COOLDOWN_SECONDS = 1.0
hand_states = {
    'Right': {'candidate': -1, 'frames': 0, 'last_sent': -1, 'last_command_time': 0.0},
    'Left': {'candidate': -1, 'frames': 0, 'last_sent': -1, 'last_command_time': 0.0},
}
ACTION_NAMES = {0: 'READY', 1: 'WAVE', 2: 'SALUTE',
                3: 'DOUBLE_STRIKE', 4: 'SWORD_SWING', 5: 'GUARD'}
UI_ACTION_NAMES = {0: '準備姿勢', 1: '揮手', 2: '敬禮',
                   3: '雙手下劈', 4: '揮劍', 5: '舉劍格擋'}
FREE_MODE_ACTION_LIST = [
    {'gesture_icon': '✊', 'gesture_name': '握拳', 'action_name': '準備姿勢', 'action_code': 'READY'},
    {'gesture_icon': '☝️', 'gesture_name': '伸出 1 根手指', 'action_name': '揮手', 'action_code': 'WAVE'},
    {'gesture_icon': '✌️', 'gesture_name': '伸出 2 根手指', 'action_name': '敬禮', 'action_code': 'SALUTE'},
    {'gesture_icon': '🤟', 'gesture_name': '伸出 3 根手指', 'action_name': '雙手下劈', 'action_code': 'DOUBLE_STRIKE'},
    {'gesture_icon': '🖐️', 'gesture_name': '伸出 4 根手指', 'action_name': '揮劍', 'action_code': 'SWORD_SWING'},
    {'gesture_icon': '🖐️', 'gesture_name': '伸出 5 根手指', 'action_name': '舉劍格擋', 'action_code': 'GUARD'},
]
system_mode = 'script'
script_generated = False
script_started = False
script_finished = False
script_current_scene = 0
script_last_action = 'NONE'
script_last_action_name = '尚未執行'
SCRIPT_NAME = '《雙俠論劍》'
SCRIPT_DESCRIPTION = '青雲與赤風以劍會友，六幕、十五組雙角色手勢操作。'
SCRIPT_SCENES = [
    {'scene_title': '江湖相遇', 'story_text': '赤風打招呼', 'gesture_count': 1, 'gesture_name': '右手 1 根', 'gesture_icon': '☝️', 'operator_text': '請比出 右手 1 根，保持穩定。', 'action_name': '赤風打招呼', 'action_code': 'R1', 'left_count': None, 'right_count': 1, 'step_number': 1},
    {'scene_title': '江湖相遇', 'story_text': '青雲行禮', 'gesture_count': 2, 'gesture_name': '左手 2 根', 'gesture_icon': '✌️', 'operator_text': '請比出 左手 2 根，保持穩定。', 'action_name': '青雲行禮', 'action_code': 'L2', 'left_count': 2, 'right_count': None, 'step_number': 2},
    {'scene_title': '江湖相遇', 'story_text': '赤風回禮', 'gesture_count': 2, 'gesture_name': '右手 2 根', 'gesture_icon': '✌️', 'operator_text': '請比出 右手 2 根，保持穩定。', 'action_name': '赤風回禮', 'action_code': 'R2', 'left_count': None, 'right_count': 2, 'step_number': 3},
    {'scene_title': '以劍會友', 'story_text': '青雲展示劍法', 'gesture_count': 4, 'gesture_name': '左手 4 根', 'gesture_icon': '🖐️', 'operator_text': '請比出 左手 4 根，保持穩定。', 'action_name': '青雲展示劍法', 'action_code': 'L4', 'left_count': 4, 'right_count': None, 'step_number': 4},
    {'scene_title': '以劍會友', 'story_text': '赤風展示劍法', 'gesture_count': 4, 'gesture_name': '右手 4 根', 'gesture_icon': '🖐️', 'operator_text': '請比出 右手 4 根，保持穩定。', 'action_name': '赤風展示劍法', 'action_code': 'R4', 'left_count': None, 'right_count': 4, 'step_number': 5},
    {'scene_title': '以劍會友', 'story_text': '雙方正式行禮', 'gesture_count': 2, 'gesture_name': '左手 2 根＋右手 2 根', 'gesture_icon': '✌️', 'operator_text': '請比出 左手 2 根＋右手 2 根，保持穩定。', 'action_name': '雙方正式行禮', 'action_code': 'DUAL', 'left_count': 2, 'right_count': 2, 'step_number': 6},
    {'scene_title': '赤風先攻', 'story_text': '赤風攻擊、青雲格擋', 'gesture_count': 3, 'gesture_name': '左手 5 根＋右手 3 根', 'gesture_icon': '🤟', 'operator_text': '請比出 左手 5 根＋右手 3 根，保持穩定。', 'action_name': '赤風攻擊、青雲格擋', 'action_code': 'DUAL', 'left_count': 5, 'right_count': 3, 'step_number': 7},
    {'scene_title': '青雲反擊', 'story_text': '青雲揮劍', 'gesture_count': 4, 'gesture_name': '左手 4 根', 'gesture_icon': '🖐️', 'operator_text': '請比出 左手 4 根，保持穩定。', 'action_name': '青雲揮劍', 'action_code': 'L4', 'left_count': 4, 'right_count': None, 'step_number': 8},
    {'scene_title': '青雲反擊', 'story_text': '青雲攻擊、赤風格擋', 'gesture_count': 5, 'gesture_name': '左手 3 根＋右手 5 根', 'gesture_icon': '🖐️', 'operator_text': '請比出 左手 3 根＋右手 5 根，保持穩定。', 'action_name': '青雲攻擊、赤風格擋', 'action_code': 'DUAL', 'left_count': 3, 'right_count': 5, 'step_number': 9},
    {'scene_title': '最終交鋒', 'story_text': '雙方同時揮劍', 'gesture_count': 4, 'gesture_name': '左手 4 根＋右手 4 根', 'gesture_icon': '🖐️', 'operator_text': '請比出 左手 4 根＋右手 4 根，保持穩定。', 'action_name': '雙方同時揮劍', 'action_code': 'DUAL', 'left_count': 4, 'right_count': 4, 'step_number': 10},
    {'scene_title': '最終交鋒', 'story_text': '赤風再次進攻、青雲格擋', 'gesture_count': 3, 'gesture_name': '左手 5 根＋右手 3 根', 'gesture_icon': '🤟', 'operator_text': '請比出 左手 5 根＋右手 3 根，保持穩定。', 'action_name': '赤風再次進攻、青雲格擋', 'action_code': 'DUAL', 'left_count': 5, 'right_count': 3, 'step_number': 11},
    {'scene_title': '最終交鋒', 'story_text': '青雲最後反擊、赤風格擋', 'gesture_count': 5, 'gesture_name': '左手 3 根＋右手 5 根', 'gesture_icon': '🖐️', 'operator_text': '請比出 左手 3 根＋右手 5 根，保持穩定。', 'action_name': '青雲最後反擊、赤風格擋', 'action_code': 'DUAL', 'left_count': 3, 'right_count': 5, 'step_number': 12},
    {'scene_title': '以武會友', 'story_text': '赤風認可對手', 'gesture_count': 2, 'gesture_name': '右手 2 根', 'gesture_icon': '✌️', 'operator_text': '請比出 右手 2 根，保持穩定。', 'action_name': '赤風認可對手', 'action_code': 'R2', 'left_count': None, 'right_count': 2, 'step_number': 13},
    {'scene_title': '以武會友', 'story_text': '青雲回禮', 'gesture_count': 2, 'gesture_name': '左手 2 根', 'gesture_icon': '✌️', 'operator_text': '請比出 左手 2 根，保持穩定。', 'action_name': '青雲回禮', 'action_code': 'L2', 'left_count': 2, 'right_count': None, 'step_number': 14},
    {'scene_title': '以武會友', 'story_text': '雙方揮手謝幕', 'gesture_count': 1, 'gesture_name': '左手 1 根＋右手 1 根', 'gesture_icon': '☝️', 'operator_text': '請比出 左手 1 根＋右手 1 根，保持穩定。', 'action_name': '雙方揮手謝幕', 'action_code': 'DUAL', 'left_count': 1, 'right_count': 1, 'step_number': 15},
]
def send_arduino_command(command):
    global arduino
    print(f'準備傳送 Arduino：{command}')
    if SIMULATION_MODE:
        print(f'[模擬指令] {command}（未發送至馬達）', flush=True)
        return True
    if arduino is None or not arduino.is_open:
        print(f'Arduino 未連線，測試命令：{command}')
        return False
    try:
        with serial_lock:
            arduino.write(f'{command}\n'.encode('utf-8'))
            arduino.flush()
        print(f'Arduino 序列埠寫入成功：{command}')
        return True
    except (serial.SerialException, serial.SerialTimeoutException, OSError) as error:
        print(f'Arduino 指令傳送失敗：{error}')
        return False
# Arduino 回覆監控：只讀取 Arduino 回傳，不改變手勢或動作排程。
def arduino_feedback_thread():
    line_buffer = bytearray()
    while True:
        if arduino is None or not arduino.is_open:
            time.sleep(0.2)
            continue
        try:
            # 共用鎖避免讀取與寫入同時操作同一序列物件；
            # in_waiting/read(size) 不等待換行，避免阻塞送指令。
            with serial_lock:
                available = arduino.in_waiting
                chunk = arduino.read(min(available, 256)) if available else b''
            if not chunk:
                time.sleep(0.01)
                continue
            for b in chunk:
                if b == 10:  # newline
                    message = line_buffer.decode('utf-8', errors='replace').strip()
                    line_buffer.clear()
                    if message:
                        print(f'[Arduino 回覆] {message}', flush=True)
                elif b != 13:  # ignore CR
                    if len(line_buffer) < 256:
                        line_buffer.append(b)
                    else:
                        line_buffer.clear()
                        print('[Arduino 回覆] 警告：回覆過長，已捨棄', flush=True)
        except (serial.SerialException, OSError) as error:
            print(f'[Arduino 回覆] 讀取失敗：{error}', flush=True)
            time.sleep(0.5)
# 管理相機子程序，避免 Ctrl+C 後殘留並占用 CSI 相機。
camera_stop_event = threading.Event()
camera_process = None
camera_process_lock = threading.Lock()
# 影像來源：預設 Raspberry Pi CSI 鏡頭；可切到預錄影片。
video_source = 'camera'
source_lock = threading.Lock()
source_epoch = [0]
video_play_event = threading.Event()
video_restart_event = threading.Event()
video_status_lock = threading.Lock()
video_status = {'status': 'inactive', 'position': 0.0, 'duration': 0.0,
                'fps': 0.0, 'message': '目前使用樹莓派鏡頭'}
VIDEO_PATH = 'static/videos/gesture_performance.mp4'
def get_video_source():
    with source_lock:
        return video_source, source_epoch[0]
def update_video_status(**fields):
    with video_status_lock:
        video_status.update(fields)
def clear_video_hand_state():
    global right_hand_finger_count, left_hand_finger_count
    global right_hand_action, left_hand_action
    global right_character_command, left_character_command
    with state_lock:
        right_hand_finger_count = None
        left_hand_finger_count = None
        right_hand_action = 'NOT_DETECTED'
        left_hand_action = 'NOT_DETECTED'
        right_character_command = 'IDLE'
        left_character_command = 'IDLE'
    for hand in ('Right', 'Left'):
        reset_hand_state(hand, clear_cooldown=True)
def publish_frame(frame):
    global latest_camera_frame, camera_frame_id
    with camera_frame_lock:
        latest_camera_frame = frame
        camera_frame_id += 1
def switch_source(target):
    global video_source, latest_camera_frame, latest_output_frame
    if target not in ('camera', 'video'):
        return False
    with source_lock:
        video_source = target
        source_epoch[0] += 1
    video_play_event.clear()
    video_restart_event.clear()
    clear_video_hand_state()
    with camera_frame_lock:
        latest_camera_frame = None
    with output_frame_lock:
        latest_output_frame = None
    global latest_visual_hands, latest_visual_time
    with visual_lock:
        latest_visual_hands = []
        latest_visual_time = 0.0
    update_video_status(status='loading' if target == 'video' else 'inactive',
                        position=0.0,
                        message='影片準備中' if target == 'video' else '目前使用樹莓派鏡頭')
    # 從 rpicam-vid 的 blocking read 中喚醒，以利切換來源。
    with camera_process_lock:
        proc = camera_process
    if proc is not None and proc.poll() is None:
        proc.terminate()
    print(f'手勢影像來源切換：{target}', flush=True)
    return True
def stop_camera_process():
    global camera_process
    camera_stop_event.set()
    with camera_process_lock:
        proc = camera_process
        camera_process = None
    if proc is not None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
atexit.register(stop_camera_process)
def handle_shutdown_signal(signum, frame):
    raise SystemExit(128 + signum)
signal.signal(signal.SIGTERM, handle_shutdown_signal)
def run_camera_source(epoch):
    global camera_process
    command = ['rpicam-vid', '-t', '0', '--inline', '--codec', 'mjpeg',
               '--nopreview', '--width', '640', '--height', '480',
               '--framerate', '30', '-o', '-']
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, bufsize=0)
    except (OSError, FileNotFoundError) as error:
        print(f'無法啟動樹莓派鏡頭：{error}', flush=True)
        time.sleep(1)
        return
    with camera_process_lock:
        camera_process = proc
    print('樹莓派 CSI 鏡頭啟動', flush=True)
    buffer = bytearray()
    try:
        while not camera_stop_event.is_set() and get_video_source() == ('camera', epoch):
            chunk = proc.stdout.read(8192)
            if not chunk:
                break
            buffer.extend(chunk)
            start = buffer.find(b'\xff\xd8')
            if start == -1:
                buffer.clear()
                continue
            if start:
                del buffer[:start]
            end = buffer.find(b'\xff\xd9', 2)
            if end != -1:
                jpeg = bytes(buffer[:end + 2])
                del buffer[:end + 2]
                frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None and get_video_source() == ('camera', epoch):
                    publish_frame(frame)
            if len(buffer) > 8_000_000:
                buffer.clear()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        with camera_process_lock:
            if camera_process is proc:
                camera_process = None
        proc.stdout.close()
        print('樹莓派 CSI 鏡頭已停止', flush=True)
def run_video_source(epoch):
    from pathlib import Path
    movie = Path(__file__).resolve().parent / VIDEO_PATH
    if not movie.is_file():
        update_video_status(status='error', message=f'找不到影片：{movie}')
        print(f'找不到影片：{movie}', flush=True)
        while not camera_stop_event.is_set() and get_video_source() == ('video', epoch):
            time.sleep(0.1)
        return
    capture = cv2.VideoCapture(str(movie))
    if not capture.isOpened():
        update_video_status(status='error', message=f'OpenCV 無法開啟：{movie}')
        while not camera_stop_event.is_set() and get_video_source() == ('video', epoch):
            time.sleep(0.1)
        return
    fps = capture.get(cv2.CAP_PROP_FPS)
    fps = fps if 1 <= fps <= 120 else 30.0
    total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    update_video_status(status='paused', position=0.0, fps=round(fps, 2),
                        duration=round(total / fps, 2), message='已就緒，請按播放影片')
    # 開始前先顯示第一格，避免網頁黑畫面；不會送出動作。
    ok, preview = capture.read()
    if ok and get_video_source() == ('video', epoch):
        publish_frame(preview)
    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frame_number = 0
    next_frame_time = time.monotonic()
    try:
        while not camera_stop_event.is_set() and get_video_source() == ('video', epoch):
            if video_restart_event.is_set():
                video_restart_event.clear()
                video_play_event.clear()
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frame_number = 0
                clear_video_hand_state()
                publish_frame(preview) if ok else None
                update_video_status(status='paused', position=0.0, message='已回到開頭')
            if not video_play_event.is_set():
                next_frame_time = time.monotonic()
                time.sleep(0.03)
                continue
            delay = next_frame_time - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 0.03))
                continue
            ok_frame, frame = capture.read()
            if not ok_frame:
                video_play_event.clear()
                clear_video_hand_state()
                update_video_status(status='ended', message='影片播放完畢')
                continue
            frame_number += 1
            if get_video_source() == ('video', epoch):
                publish_frame(frame)
            update_video_status(status='playing', position=round(frame_number / fps, 2), message='')
            next_frame_time += 1.0 / fps
            if next_frame_time < time.monotonic() - 0.15:
                next_frame_time = time.monotonic()
    finally:
        capture.release()
        video_play_event.clear()
        print('影片來源已釋放', flush=True)
def camera_thread():
    while not camera_stop_event.is_set():
        source, epoch = get_video_source()
        if source == 'camera':
            run_camera_source(epoch)
        else:
            run_video_source(epoch)
        time.sleep(0.05)
@app.route('/set_video_source', methods=['POST'])
def set_video_source():
    data = request.get_json(silent=True) or {}
    source = data.get('source')
    if source not in ('camera', 'video'):
        return jsonify({'success': False, 'message': 'source 必須是 camera 或 video'}), 400
    switch_source(source)
    return jsonify({'success': True, 'source': source})
@app.route('/video_control', methods=['POST'])
def video_control():
    if get_video_source()[0] != 'video':
        return jsonify({'success': False, 'message': '請先切換至影片來源'}), 409
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    with video_status_lock:
        current = video_status['status']
    if action == 'play':
        if current in ('loading', 'error'):
            return jsonify({'success': False, 'message': '影片尚未就緒'}), 400
        if current == 'ended':
            return jsonify({'success': False, 'message': '影片已結束，請先回到開頭'}), 400
        video_play_event.set()
        update_video_status(status='playing', message='')
    elif action == 'pause':
        video_play_event.clear()
        update_video_status(status='paused', message='已暫停')
    elif action == 'restart':
        video_restart_event.set()
    else:
        return jsonify({'success': False, 'message': 'action 必須是 play / pause / restart'}), 400
    return jsonify({'success': True})
def count_fingers(hand_landmarks):
    landmarks = hand_landmarks.landmark
    count = 0
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        if landmarks[tip].y < landmarks[pip].y:
            count += 1
    thumb_tip_distance = np.hypot(landmarks[4].x - landmarks[17].x,
                                   landmarks[4].y - landmarks[17].y)
    thumb_joint_distance = np.hypot(landmarks[3].x - landmarks[17].x,
                                     landmarks[3].y - landmarks[17].y)
    if thumb_tip_distance > thumb_joint_distance:
        count += 1
    return count
def get_hand_action_name(finger_count):
    return ACTION_NAMES.get(finger_count, 'UNKNOWN')
def reset_hand_state(hand_label, *, clear_cooldown=False):
    state = hand_states[hand_label]
    state['candidate'] = -1
    state['frames'] = 0
    state['last_sent'] = -1
    # Tracking interruption must NOT bypass the 1-second cooldown.
    # This flag is only for an explicit new session if ever needed.
    if clear_cooldown:
        state['last_command_time'] = 0.0
def analyze_hand_gesture(hand_label, finger_count):
    """單手穩定偵測；自由模式直接派送，劇本模式交由整步判斷。"""
    global right_character_command, left_character_command
    state = hand_states[hand_label]
    now = time.monotonic()
    if finger_count not in (1, 2, 3, 4, 5):
        state['candidate'] = -1
        state['frames'] = 0
        state['last_sent'] = -1
        return
    if finger_count != state['candidate']:
        state['candidate'] = finger_count
        state['frames'] = 1
    else:
        state['frames'] += 1
    with state_lock:
        mode = system_mode
    if mode != 'free' or state['frames'] < STABLE_FRAMES_REQUIRED:
        return
    if finger_count == state['last_sent']:
        return
    if now - state['last_command_time'] < COMMAND_COOLDOWN_SECONDS:
        return
    command = ('R' if hand_label == 'Right' else 'L') + str(finger_count)
    if not send_arduino_command(command):
        return
    state['last_sent'] = finger_count
    state['last_command_time'] = time.monotonic()
    with state_lock:
        if hand_label == 'Right':
            right_character_command = command
        else:
            left_character_command = command
def process_script_step():
    """以完整左右手組合確認每一組動作，避免雙手動作只送出一半。"""
    global script_started, script_finished, script_current_scene
    global script_last_action, script_last_action_name
    global right_character_command, left_character_command
    with state_lock:
        if (system_mode != 'script' or not script_started or script_finished
                or script_current_scene >= len(SCRIPT_SCENES)):
            return
        step_index = script_current_scene
        step = SCRIPT_SCENES[step_index]
    for hand, key in (('Left','left_count'), ('Right','right_count')):
        expected = step[key]
        if expected is None:
            continue
        hs = hand_states[hand]
        if hs['candidate'] != expected or hs['frames'] < STABLE_FRAMES_REQUIRED:
            return
    # 每組指令發送間隔至少 1 秒，以免前一組相同角色還未完成。
    now = time.monotonic()
    if now - script_last_dispatch_time[0] < COMMAND_COOLDOWN_SECONDS:
        return
    commands = []
    if step['left_count'] is not None:
        commands.append('L' + str(step['left_count']))
    if step['right_count'] is not None:
        commands.append('R' + str(step['right_count']))
    with script_dispatch_lock:
        with state_lock:
            if not script_started or script_current_scene != step_index:
                return
        for command in commands:
            if not send_arduino_command(command):
                print('劇本指令失敗，請確認 Arduino 連線：' + command)
                return
        script_last_dispatch_time[0] = time.monotonic()
        with state_lock:
            if step['left_count'] is not None:
                left_character_command = 'L' + str(step['left_count'])
            if step['right_count'] is not None:
                right_character_command = 'R' + str(step['right_count'])
            script_last_action = step['action_code']
            script_last_action_name = step['action_name']
            script_current_scene += 1
            if script_current_scene >= len(SCRIPT_SCENES):
                script_finished = True
                script_started = False
        print(f"劇本步驟 {step_index+1}/{len(SCRIPT_SCENES)}：{', '.join(commands)}")
script_dispatch_lock = threading.Lock()
script_last_dispatch_time = [0.0]
def vision_thread():
    global latest_visual_hands, latest_visual_time, latest_ai_fps
    global right_hand_finger_count, left_hand_finger_count
    global right_hand_action, left_hand_action
    global right_character_command, left_character_command
    frame_count = 0
    last_processed_frame_id = -1
    fps_start_time = time.time()
    fps = 0.0
    while True:
        with camera_frame_lock:
            frame = latest_camera_frame.copy() if latest_camera_frame is not None else None
            current_frame_id = camera_frame_id
        if frame is None:
            time.sleep(0.01)
            continue
        if current_frame_id == last_processed_frame_id:
            time.sleep(0.005)
            continue
        last_processed_frame_id = current_frame_id
        if VIDEO_MIRROR:
            frame = cv2.flip(frame, 1)
        frame_count += 1
        if frame_count % 10 == 0:
            elapsed_time = time.time() - fps_start_time
            if elapsed_time > 0:
                fps = round(10 / elapsed_time, 1)
            fps_start_time = time.time()
        if frame_count % 2 == 0:
            visual_hands = []
            # 只縮小 MediaPipe 的辨識輸入
            # 網頁輸出仍使用原始 frame
            detection_frame = cv2.resize(
                frame, (480, 360),
                interpolation=cv2.INTER_AREA
            )
            image_rgb = cv2.cvtColor(
                detection_frame, cv2.COLOR_BGR2RGB
            )
            results = hands.process(image_rgb)
            seen_hands = set()
            if results.multi_hand_landmarks:
                for hand_landmarks, handedness in zip(
                        results.multi_hand_landmarks, results.multi_handedness):
                    hand_label = handedness.classification[0].label
                    seen_hands.add(hand_label)

                    finger_count = count_fingers(hand_landmarks)
                    action_name = get_hand_action_name(finger_count)
                    visual_hands.append((
                        [(pt.x, pt.y) for pt in hand_landmarks.landmark],
                        hand_label, finger_count, action_name
                    ))
                    with state_lock:
                        if hand_label == 'Right':
                            right_hand_finger_count = finger_count
                            right_hand_action = action_name
                        elif hand_label == 'Left':
                            left_hand_finger_count = finger_count
                            left_hand_action = action_name
                    if hand_label in hand_states:
                        if get_video_source()[0] == 'camera' or video_play_event.is_set():
                            analyze_hand_gesture(hand_label, finger_count)

            if 'Right' not in seen_hands:
                with state_lock:
                    right_hand_finger_count = None
                    right_hand_action = 'NOT_DETECTED'
                    right_character_command = 'IDLE'
                reset_hand_state('Right')
            if 'Left' not in seen_hands:
                with state_lock:
                    left_hand_finger_count = None
                    left_hand_action = 'NOT_DETECTED'
                    left_character_command = 'IDLE'
                reset_hand_state('Left')
        if frame_count % 2 == 0:
            if get_video_source()[0] == 'camera' or video_play_event.is_set():
                process_script_step()
            with visual_lock:
                latest_visual_hands = visual_hands
                latest_visual_time = time.monotonic()
                latest_ai_fps = fps / 2.0
        time.sleep(0.002)


def preview_thread():
    """獨立產生 640×480 CSI 預覽，不卡在 AI 推論；顯示最新辨識骨架。"""
    global latest_output_frame, latest_output_seq
    last_frame_id = -1
    last_source = None
    next_time = 0.0
    count = 0
    fps_start = time.monotonic()
    preview_fps = 0.0
    links = list(mp_hands.HAND_CONNECTIONS)
    while True:
        now = time.monotonic()
        if now < next_time:
            time.sleep(min(0.01, next_time - now))
            continue
        with camera_frame_lock:
            frame_id = camera_frame_id
            frame = latest_camera_frame.copy() if latest_camera_frame is not None else None
        source = get_video_source()
        if frame is None:
            last_frame_id = -1
            time.sleep(0.01)
            continue
        if frame_id == last_frame_id and source == last_source:
            time.sleep(0.005)
            continue
        last_frame_id, last_source = frame_id, source
        # 維持原比例；CSI 640×480，16:9 影片則縮為 640×360。
        height, width = frame.shape[:2]
        scale = min(1.0, 640 / width, 480 / height)
        if scale < 1.0:
            frame = cv2.resize(frame, (round(width * scale), round(height * scale)),
                               interpolation=cv2.INTER_AREA)
        if VIDEO_MIRROR:
            frame = cv2.flip(frame, 1)
        height, width = frame.shape[:2]
        with visual_lock:
            hands_to_draw = list(latest_visual_hands)
            hand_age = now - latest_visual_time
            ai_fps = latest_ai_fps
        if 0 <= hand_age < 0.35:
            for coords, label, fingers, action in hands_to_draw:
                points = [(int(x * width), int(y * height)) for x, y in coords]
                for a, b in links:
                    cv2.line(frame, points[a], points[b], (0, 255, 0), 2)
                for point in points:
                    cv2.circle(frame, point, 3, (0, 220, 255), -1)
                if points:
                    x, y = points[0]
                    cv2.putText(frame, f'{label}: {fingers} / {action}',
                                (max(5, x), max(20, y - 15)), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (0, 255, 255), 2)
        count += 1
        elapsed = now - fps_start
        if elapsed >= 1.0:
            preview_fps = count / elapsed
            count, fps_start = 0, now
        with state_lock:
            r_count, l_count = right_hand_finger_count, left_hand_finger_count
            r_action, l_action = right_hand_action, left_hand_action
            r_cmd, l_cmd = right_character_command, left_character_command
        for text, pos, color in (
            (f'Preview: {preview_fps:.1f} FPS  AI: {ai_fps:.1f} FPS', (10, 25), (0, 255, 0)),
            (f'P1 Right: {r_count if r_count is not None else "-"} / {r_action}', (10, 60), (255, 255, 0)),
            (f'P2 Left: {l_count if l_count is not None else "-"} / {l_action}', (10, 95), (255, 255, 0)),
            (f'P1 CMD: {r_cmd}', (10, 130), (0, 0, 255)),
            (f'P2 CMD: {l_cmd}', (10, 165), (255, 0, 255)),
        ):
            cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        ok, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_JPEG_QUALITY])
        if ok and source == get_video_source():
            with output_frame_lock:
                latest_output_frame = jpeg.tobytes()
                latest_output_seq += 1
        next_time = time.monotonic() + 1.0 / PREVIEW_FPS_LIMIT


def generate_frames():
    last_seq = -1
    while True:
        with output_frame_lock:
            jpeg = latest_output_frame
            seq = latest_output_seq
        if jpeg is None or seq == last_seq:
            time.sleep(0.01)
            continue
        last_seq = seq
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n'
               + jpeg + b'\r\n')



def generate_puppet_frames():
    while True:
        with puppet_frame_lock:
            frame = puppet_frame
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n'
               + frame + b'\r\n')
        time.sleep(0.03)
@app.route('/')
def index():
    return render_template('index.html')
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')
@app.route('/phone')
def phone_camera():
    return render_template('phone.html')
@app.route('/phone_frame', methods=['POST'])
def phone_frame():
    global puppet_frame, puppet_frame_time
    if request.mimetype != 'image/jpeg':
        return 'Content-Type 必須是 image/jpeg', 400
    jpeg_data = request.get_data()
    if not jpeg_data:
        return '沒有收到影像', 400
    with puppet_frame_lock:
        puppet_frame = jpeg_data
        puppet_frame_time = time.time()
    return '', 204
@app.route('/puppet_video_feed')
def puppet_video_feed():
    return Response(generate_puppet_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')
@app.route('/viewer')
def viewer():
    return Response('''<!doctype html>
<html lang="zh-TW"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>實體戲偶接收畫面</title>
<style>body{margin:0;background:#111;color:white;font-family:sans-serif;text-align:center}
h1{font-size:20px;margin:14px 0}img{width:100%;max-width:1000px;height:auto;display:block;margin:0 auto}</style>
</head><body><h1>實體戲偶接收畫面</h1>
<img src="/puppet_video_feed" alt="實體戲偶即時影像"></body></html>''',
                    mimetype='text/html')
@app.route('/set_mode', methods=['POST'])
def set_mode():
    global system_mode, right_character_command, left_character_command, script_started
    data = request.get_json(silent=True) or {}
    mode = data.get('mode')
    if mode not in ('script', 'free'):
        return jsonify({'success': False, 'message': 'mode 必須是 script 或 free'}), 400
    with state_lock:
        system_mode = mode
        right_character_command = 'IDLE'
        left_character_command = 'IDLE'
        if mode == 'free':
            script_started = False
    reset_hand_state('Right')
    reset_hand_state('Left')
    if mode == 'free' and get_video_source()[0] != 'camera':
        switch_source('camera')
    print(f'模式切換：{system_mode}')
    return jsonify({'success': True, 'mode': system_mode})
@app.route('/load_script', methods=['POST'])
def load_script():
    global system_mode, script_generated, script_started, script_finished
    global script_current_scene, script_last_action, script_last_action_name
    with state_lock:
        system_mode = 'script'
        script_generated = True
        script_started = False
        script_finished = False
        script_current_scene = 0
        script_last_action = 'NONE'
        script_last_action_name = '尚未執行'
    reset_hand_state('Right')
    reset_hand_state('Left')
    script_last_dispatch_time[0] = 0.0
    print('劇本已載入：《雙俠論劍》')
    return jsonify({'success': True, 'script_name': SCRIPT_NAME,
                    'total_scenes': len(SCRIPT_SCENES)})
@app.route('/start_script', methods=['POST'])
def start_script():
    global system_mode, script_started, script_finished
    global script_current_scene, script_last_action, script_last_action_name
    with state_lock:
        if not script_generated:
            return jsonify({'success': False, 'message': '請先載入劇本。'})
        system_mode = 'script'
        script_started = True
        script_finished = False
        script_current_scene = 0
        script_last_action = 'NONE'
        script_last_action_name = '尚未執行'
    reset_hand_state('Right')
    reset_hand_state('Left')
    script_last_dispatch_time[0] = 0.0
    print('劇本開始：《雙俠論劍》')
    return jsonify({'success': True})
@app.route('/state')
def state():
    current_time = time.time()
    with puppet_frame_lock:
        last_puppet_frame_time = puppet_frame_time
    puppet_connected = (last_puppet_frame_time is not None and
                        (current_time - last_puppet_frame_time) < 3.0)
    with state_lock:
        mode = system_mode
        right_fingers, left_fingers = right_hand_finger_count, left_hand_finger_count
        right_action, left_action = right_hand_action, left_hand_action
        right_command, left_command = right_character_command, left_character_command
        generated, started, finished = script_generated, script_started, script_finished
        current_scene, last_action = script_current_scene, script_last_action
        last_action_name = script_last_action_name
    if right_fingers is not None:
        detected_count, detected_hand = right_fingers, 'Right'
        detected_action = UI_ACTION_NAMES.get(right_fingers, right_action)
    elif left_fingers is not None:
        detected_count, detected_hand = left_fingers, 'Left'
        detected_action = UI_ACTION_NAMES.get(left_fingers, left_action)
    else:
        detected_count, detected_hand, detected_action = None, None, '尚未偵測'
    scene = None
    if generated and not finished and 0 <= current_scene < len(SCRIPT_SCENES):
        scene = SCRIPT_SCENES[current_scene]
    with video_status_lock:
        video_snapshot = dict(video_status)
    return jsonify({
        'video': video_snapshot,
        'video_source': get_video_source()[0],
        'puppet_connected': puppet_connected, 'mode': mode,
        'detected_count': detected_count, 'detected_hand': detected_hand,
        'current_detected_action': detected_action, 'free_actions': FREE_MODE_ACTION_LIST,
        'arduino_connected': arduino is not None and arduino.is_open,
        'simulation_mode': SIMULATION_MODE,
        'character_1': {'hand': 'Right', 'finger_count': right_fingers,
                        'action': right_action, 'command': right_command},
        'character_2': {'hand': 'Left', 'finger_count': left_fingers,
                        'action': left_action, 'command': left_command},
        'generated': generated, 'started': started, 'finished': finished,
        'script_name': SCRIPT_NAME, 'script_description': SCRIPT_DESCRIPTION,
        'current_scene': current_scene,
        'total_scenes': len(SCRIPT_SCENES) if generated else 0,
        'scene': scene, 'last_action': last_action,
        'last_action_name': last_action_name,
    })
@app.route('/get_command')
def get_command():
    with state_lock:
        data = {
            'character_1': {'hand': 'Right', 'finger_count': right_hand_finger_count,
                            'action': right_hand_action, 'command': right_character_command},
            'character_2': {'hand': 'Left', 'finger_count': left_hand_finger_count,
                            'action': left_hand_action, 'command': left_character_command},
            'arduino_connected': arduino is not None and arduino.is_open,
        }
    return jsonify(data)
if __name__ == '__main__':
    threading.Thread(target=arduino_feedback_thread, daemon=True).start()
    threading.Thread(target=camera_thread, daemon=True).start()  # 動態影像來源
    threading.Thread(target=vision_thread, daemon=True).start()
    threading.Thread(target=preview_thread, daemon=True).start()
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True, debug=False,
                use_reloader=False, ssl_context=('certs/cert.pem', 'certs/key.pem'))
    finally:
        stop_camera_process()
        if arduino is not None and arduino.is_open:
            arduino.close()
        print('掌中智戲已關閉並釋放相機、序列埠', flush=True)
