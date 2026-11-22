
# test_capture.py
# 掌中智戲｜第四章圖 4-1 測試中心
# 不主動控制馬達，只紀錄測試資料與照片

import csv
import io
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    jsonify,
    render_template_string,
    request,
    send_file
)

bp = Blueprint("chapter4_test", __name__)

ROOT = Path(__file__).resolve().parent / "test_logs" / "figure_4_1"
LOCK = threading.Lock()
SNAPSHOT_CALLBACK = None

VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
VALID_COMMAND = re.compile(r"^[RL][1-5]$")

CSV_FIELDS = [
    "trial_id",
    "expected",
    "created_at",
    "finished_at",
    "gesture_correct",
    "command_correct",
    "actual_command",
    "puppet_result",
    "note"
]


def now_text():
    return datetime.now().astimezone().isoformat(
        timespec="milliseconds"
    )


def get_folder(trial_id):
    if not VALID_ID.fullmatch(str(trial_id)):
        raise ValueError("試次編號只能使用英數字、_、-")
    return ROOT / trial_id


def read_trial(folder):
    path = folder / "trial.json"
    if not path.exists():
        raise FileNotFoundError("找不到試次")
    return json.loads(path.read_text(encoding="utf-8"))


def save_trial(folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "trial.json"
    temp = folder / "trial.json.tmp"
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp.replace(path)


def install_test_capture(app, snapshot_callback):
    global SNAPSHOT_CALLBACK
    SNAPSHOT_CALLBACK = snapshot_callback
    app.register_blueprint(bp)


PAGE = """
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>掌中智戲｜第四章測試中心</title>

<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 18px;
    background: #111827;
    color: #f3f4f6;
    font-family: Arial, sans-serif;
}

main {
    max-width: 1150px;
    margin: auto;
}

h1 { font-size: 26px; }

h2 {
    font-size: 19px;
    margin-top: 5px;
}

.panel {
    background: #1f2937;
    padding: 18px;
    border-radius: 14px;
    margin: 16px 0;
}

.cameras {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
}

.camera-box {
    background: #111827;
    padding: 10px;
    border-radius: 10px;
}

.camera-box img {
    display: block;
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: contain;
    background: #000;
}

label {
    display: block;
    margin: 10px 0 5px;
}

input, select, textarea {
    width: 100%;
    padding: 10px;
    background: #374151;
    color: white;
    border: 1px solid #6b7280;
    border-radius: 7px;
    font-size: 16px;
}

button, .download {
    display: inline-block;
    border: none;
    background: #2563eb;
    color: white;
    padding: 12px 16px;
    border-radius: 8px;
    cursor: pointer;
    margin: 5px 5px 5px 0;
    text-decoration: none;
    font-size: 15px;
}

button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.secondary { background: #475569; }
.green { background: #059669; }

#message {
    white-space: pre-wrap;
    color: #93c5fd;
    min-height: 30px;
}

.photos {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}

.photos img {
    width: 100%;
    background: #000;
    border-radius: 8px;
}

small { color: #9ca3af; }

@media(max-width: 700px) {
    .cameras, .photos {
        grid-template-columns: 1fr;
    }
}
</style>
</head>

<body>
<main>

<h1>掌中智戲｜第四章測試中心</h1>
<p>圖 4-1：手勢辨識與實體戲偶動作對應紀錄</p>

<div class="panel">
    <h2>兩路即時畫面</h2>

    <div class="cameras">
        <div class="camera-box">
            <p>手勢辨識預覽</p>
            <img src="/video_feed" alt="手勢畫面">
        </div>

        <div class="camera-box">
            <p>實體戲偶舞台</p>
            <img src="/puppet_video_feed" alt="戲偶畫面">
        </div>
    </div>

    <p id="liveState">辨識狀態讀取中...</p>
</div>

<div class="panel">
    <h2>1. 建立測試試次</h2>

    <label>試次編號</label>
    <input id="trialId" value="R1_001">

    <label>預期指令</label>
    <select id="expected">
        <option value="R1">R1｜右手1指｜揮手</option>
        <option value="R2">R2｜右手2指｜敬禮</option>
        <option value="R3">R3｜右手3指｜雙手下劈</option>
        <option value="R4">R4｜右手4指｜揮劍</option>
        <option value="R5">R5｜右手5指｜格擋</option>
        <option value="L1">L1｜左手1指｜揮手</option>
        <option value="L2">L2｜左手2指｜敬禮</option>
        <option value="L3">L3｜左手3指｜雙手下劈</option>
        <option value="L4">L4｜左手4指｜揮劍</option>
        <option value="L5">L5｜左手5指｜格擋</option>
    </select>

    <button onclick="startTrial()">建立試次</button>
</div>

<div class="panel">
    <h2>2. 擷取動作前後畫面</h2>

    <button onclick="captureTrial('before')">
        擷取動作前
    </button>

    <button onclick="captureTrial('after')" class="green">
        擷取動作後
    </button>

    <p>
        <small>
            請在戲偶動作前、動作後分別按一次。
            這不是自動判斷馬達完成時間。
        </small>
    </p>

    <div class="photos">
        <div>
            <p>動作前：手勢畫面</p>
            <img id="beforeGesture" alt="尚未擷取">
        </div>

        <div>
            <p>動作前：戲偶畫面</p>
            <img id="beforePuppet" alt="尚未擷取">
        </div>

        <div>
            <p>動作後：手勢畫面</p>
            <img id="afterGesture" alt="尚未擷取">
        </div>

        <div>
            <p>動作後：戲偶畫面</p>
            <img id="afterPuppet" alt="尚未擷取">
        </div>
    </div>
</div>

<div class="panel">
    <h2>3. 紀錄測試結果</h2>

    <label>手勢辨識是否正確</label>
    <select id="gestureCorrect">
        <option value="yes">正確</option>
        <option value="no">錯誤</option>
        <option value="unknown">尚未確認</option>
    </select>

    <label>Arduino 指令是否派送正確</label>
    <select id="commandCorrect">
        <option value="yes">正確</option>
        <option value="no">錯誤</option>
        <option value="unknown">尚未確認</option>
    </select>

    <label>實際派送指令</label>
    <input id="actualCommand"
           placeholder="例如 R1；若未派送請留空">

    <label>實體戲偶結果</label>
    <select id="puppetResult">
        <option value="success">正確完成</option>
        <option value="wrong">動作錯誤</option>
        <option value="no_action">沒有動作</option>
        <option value="timeout">逾時</option>
    </select>

    <label>備註</label>
    <textarea id="note" rows="3"
              placeholder="例如魚線鬆弛、手勢誤判"></textarea>

    <button onclick="finishTrial()" class="green">
        完成並保存試次
    </button>
</div>

<div class="panel">
    <h2>4. 匯出測試資料</h2>

    <a class="download"
       href="/test/api/export.csv">
       下載全部試次 CSV
    </a>

    <button class="secondary" onclick="listTrials()">
        查看已儲存試次
    </button>

    <pre id="trials"></pre>
</div>

<div class="panel">
    <h2>操作訊息</h2>
    <p id="message">尚未開始測試</p>
</div>

</main>

<script>
"use strict";

function value(id) {
    return document.getElementById(id).value;
}

function showMessage(message) {
    document.getElementById("message").textContent =
        message;
}

async function api(path, data) {
    const response = await fetch(path, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(data)
    });

    const result = await response.json();

    if (!response.ok || !result.ok) {
        throw new Error(
            result.error || "伺服器處理失敗"
        );
    }

    return result;
}

async function startTrial() {
    try {
        const result = await api("/test/api/start", {
            trial_id: value("trialId"),
            expected: value("expected")
        });

        showMessage(
            "已建立試次：" +
            result.trial.trial_id
        );

    } catch (error) {
        showMessage(error.message);
    }
}

async function captureTrial(stage) {
    try {
        const id = value("trialId");

        await api("/test/api/capture", {
            trial_id: id,
            stage: stage
        });

        const timestamp = Date.now();

        const prefix =
            "/test/media/" +
            encodeURIComponent(id) + "/";

        const gesture = document.getElementById(
            stage === "before"
                ? "beforeGesture"
                : "afterGesture"
        );

        const puppet = document.getElementById(
            stage === "before"
                ? "beforePuppet"
                : "afterPuppet"
        );

        gesture.src =
            prefix + stage +
            "_gesture.jpg?t=" + timestamp;

        puppet.src =
            prefix + stage +
            "_puppet.jpg?t=" + timestamp;

        showMessage(
            (stage === "before"
                ? "動作前"
                : "動作後") +
            "照片已儲存"
        );

    } catch (error) {
        showMessage(error.message);
    }
}

async function finishTrial() {
    try {
        await api("/test/api/finish", {
            trial_id: value("trialId"),
            gesture_correct: value("gestureCorrect"),
            command_correct: value("commandCorrect"),
            actual_command: value("actualCommand"),
            puppet_result: value("puppetResult"),
            note: value("note")
        });

        showMessage("本次試次已完成並保存");

    } catch (error) {
        showMessage(error.message);
    }
}

async function listTrials() {
    try {
        const response = await fetch("/test/api/list");
        const data = await response.json();

        document.getElementById("trials").textContent =
            data.trials.map(t =>
                t.trial_id + " | " +
                t.expected + " | " +
                t.status
            ).join("\\n") || "尚無紀錄";

    } catch (error) {
        showMessage(error.message);
    }
}

async function updateState() {
    try {
        const response = await fetch("/state");
        const data = await response.json();

        document.getElementById("liveState").textContent =
            "右手：" +
            (data.character_1?.finger_count ?? "-") +
            "，指令：" +
            (data.character_1?.command ?? "-") +
            "｜左手：" +
            (data.character_2?.finger_count ?? "-") +
            "，指令：" +
            (data.character_2?.command ?? "-");

    } catch (error) {
        document.getElementById("liveState").textContent =
            "狀態讀取失敗";
    }
}

updateState();
setInterval(updateState, 1000);
</script>
</body>
</html>
"""


@bp.route("/test")
def test_page():
    return render_template_string(PAGE)


@bp.route("/test/api/start", methods=["POST"])
def start_trial():
    data = request.get_json(silent=True) or {}

    trial_id = str(data.get("trial_id", "")).strip()
    expected = str(data.get("expected", "")).upper()

    if not VALID_COMMAND.fullmatch(expected):
        return jsonify(
            ok=False,
            error="預期指令必須是 R1～R5 或 L1～L5"
        ), 400

    try:
        folder = get_folder(trial_id)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400

    with LOCK:
        if folder.exists():
            return jsonify(
                ok=False,
                error="試次已存在，請換編號"
            ), 409

        trial = {
            "trial_id": trial_id,
            "expected": expected,
            "created_at": now_text(),
            "finished_at": "",
            "gesture_correct": "",
            "command_correct": "",
            "actual_command": "",
            "puppet_result": "",
            "note": "",
            "status": "started"
        }

        save_trial(folder, trial)

    return jsonify(ok=True, trial=trial)


@bp.route("/test/api/capture", methods=["POST"])
def capture_trial():
    data = request.get_json(silent=True) or {}

    trial_id = str(data.get("trial_id", "")).strip()
    stage = str(data.get("stage", "")).lower()

    if stage not in ("before", "after"):
        return jsonify(
            ok=False,
            error="stage 必須是 before 或 after"
        ), 400

    try:
        folder = get_folder(trial_id)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400

    if SNAPSHOT_CALLBACK is None:
        return jsonify(
            ok=False,
            error="尚未連接 app.py"
        ), 503

    # 取得當下兩路影像與系統狀態
    gesture, puppet, state, puppet_age = (
        SNAPSHOT_CALLBACK()
    )

    if not gesture or not puppet:
        return jsonify(
            ok=False,
            error="請先開啟兩路攝影機"
        ), 409

    if puppet_age is None or puppet_age > 3:
        return jsonify(
            ok=False,
            error="手機影像已停止更新"
        ), 409

    with LOCK:
        try:
            trial = read_trial(folder)
        except FileNotFoundError:
            return jsonify(
                ok=False,
                error="請先建立試次"
            ), 404

        if trial["status"] == "finished":
            return jsonify(
                ok=False,
                error="試次已結束"
            ), 409

        if trial.get(stage + "_time"):
            return jsonify(
                ok=False,
                error="此階段已擷取，不能覆寫"
            ), 409

        if stage == "after" and not trial.get(
            "before_time"
        ):
            return jsonify(
                ok=False,
                error="請先擷取動作前"
            ), 409

        # 保存原始 JPEG
        (folder / f"{stage}_gesture.jpg").write_bytes(
            gesture
        )

        (folder / f"{stage}_puppet.jpg").write_bytes(
            puppet
        )

        trial[stage + "_time"] = now_text()
        trial[stage + "_state"] = state
        trial[stage + "_puppet_age_ms"] = round(
            puppet_age * 1000
        )

        save_trial(folder, trial)

    return jsonify(ok=True, trial=trial)


@bp.route("/test/api/finish", methods=["POST"])
def finish_trial():
    data = request.get_json(silent=True) or {}

    try:
        folder = get_folder(
            str(data.get("trial_id", "")).strip()
        )
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400

    puppet_result = str(
        data.get("puppet_result", "")
    )

    if puppet_result not in (
        "success", "wrong", "no_action", "timeout"
    ):
        return jsonify(
            ok=False,
            error="請選擇實體戲偶結果"
        ), 400

    gesture_correct = str(
        data.get("gesture_correct", "unknown")
    )

    command_correct = str(
        data.get("command_correct", "unknown")
    )

    if (
        gesture_correct not in ("yes", "no", "unknown")
        or command_correct not in ("yes", "no", "unknown")
    ):
        return jsonify(
            ok=False,
            error="辨識與派送判定不正確"
        ), 400

    actual_command = str(
        data.get("actual_command", "")
    ).strip().upper()

    if actual_command and not VALID_COMMAND.fullmatch(
        actual_command
    ):
        return jsonify(
            ok=False,
            error="實際指令格式不正確"
        ), 400

    with LOCK:
        try:
            trial = read_trial(folder)
        except FileNotFoundError:
            return jsonify(
                ok=False,
                error="找不到試次"
            ), 404

        if trial["status"] == "finished":
            return jsonify(
                ok=False,
                error="此試次已完成"
            ), 409

        trial.update({
            "finished_at": now_text(),
            "gesture_correct": gesture_correct,
            "command_correct": command_correct,
            "actual_command": actual_command,
            "puppet_result": puppet_result,
            "note": str(data.get("note", ""))[:1000],
            "status": "finished"
        })

        save_trial(folder, trial)

    return jsonify(ok=True, trial=trial)


def load_all_trials():
    result = []

    if ROOT.exists():
        for folder in ROOT.iterdir():
            if not folder.is_dir():
                continue

            try:
                result.append(read_trial(folder))
            except (
                FileNotFoundError,
                json.JSONDecodeError
            ):
                pass

    return sorted(
        result,
        key=lambda item: item.get("created_at", ""),
        reverse=True
    )


@bp.route("/test/api/list")
def list_trials():
    with LOCK:
        trials = load_all_trials()

    return jsonify(ok=True, trials=trials)


@bp.route("/test/api/export.csv")
def export_trials():
    with LOCK:
        trials = load_all_trials()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=CSV_FIELDS,
        extrasaction="ignore"
    )

    writer.writeheader()

    for trial in trials:
        writer.writerow(trial)

    return Response(
        "\\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                'attachment; filename="puppet_trials.csv"'
        }
    )


@bp.route("/test/media/<trial_id>/<filename>")
def test_image(trial_id, filename):
    allowed = {
        "before_gesture.jpg",
        "before_puppet.jpg",
        "after_gesture.jpg",
        "after_puppet.jpg"
    }

    if filename not in allowed:
        return jsonify(
            ok=False,
            error="不允許的檔案"
        ), 404

    try:
        folder = get_folder(trial_id)
    except ValueError:
        return jsonify(
            ok=False,
            error="試次編號錯誤"
        ), 400

    path = folder / filename

    if not path.is_file():
        return jsonify(
            ok=False,
            error="圖片不存在"
        ), 404

    return send_file(
        path,
        mimetype="image/jpeg",
        max_age=0
    )
