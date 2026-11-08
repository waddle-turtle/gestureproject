
"use strict";

// =====================================================
// 掌中智戲｜手機實體戲偶攝影機
// 功能：手機拍攝、JPEG 上傳、效能監控
// =====================================================

// DOM 元件
const video = document.querySelector("#camera");
const canvas = document.querySelector("#capture");
const context = canvas.getContext("2d", { alpha: false });

const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const facing = document.querySelector("#facing");
const fps = document.querySelector("#fps");
const statusText = document.querySelector("#status");

// =====================================================
// 基本設定
// =====================================================

const JPEG_QUALITY = 0.50;
const MAX_IMAGE_SIZE = 480;
const UPLOAD_TIMEOUT_MS = 5000;
const METRICS_INTERVAL_MS = 5000;

// 攝影機與傳輸狀態
let stream = null;
let session = 0;
let upload = null;
let timer = null;

// =====================================================
// 效能監控
// =====================================================

let metricsStart = 0;

let successFrames = 0;
let failedFrames = 0;

let totalEncodeMs = 0;
let totalUploadMs = 0;
let totalFrameKB = 0;

let latestMessage = "尚未開啟鏡頭";

function resetMetrics() {
    metricsStart = performance.now();

    successFrames = 0;
    failedFrames = 0;

    totalEncodeMs = 0;
    totalUploadMs = 0;
    totalFrameKB = 0;
}

function updateMetrics(force = false) {
    const elapsed = performance.now() - metricsStart;

    if (!force && elapsed < METRICS_INTERVAL_MS) {
        return;
    }

    const seconds = Math.max(elapsed / 1000, 0.001);

    const actualFPS = successFrames / seconds;

    const averageEncode =
        successFrames > 0
            ? totalEncodeMs / successFrames
            : 0;

    const averageUpload =
        successFrames > 0
            ? totalUploadMs / successFrames
            : 0;

    const averageKB =
        successFrames > 0
            ? totalFrameKB / successFrames
            : 0;

    statusText.textContent =
        `${latestMessage}\n` +
        `實際上傳 FPS：${actualFPS.toFixed(1)}\n` +
        `JPEG 大小：${averageKB.toFixed(1)} KB\n` +
        `JPEG 編碼：${averageEncode.toFixed(1)} ms\n` +
        `上傳往返：${averageUpload.toFixed(1)} ms\n` +
        `失敗次數：${failedFrames}`;

    statusText.style.whiteSpace = "pre-line";

    console.log("[掌中智戲手機串流]", {
        fps: actualFPS.toFixed(1),
        jpegKB: averageKB.toFixed(1),
        encodeMs: averageEncode.toFixed(1),
        uploadMs: averageUpload.toFixed(1),
        failures: failedFrames
    });

    resetMetrics();
}

// =====================================================
// 停止攝影機
// =====================================================

function stopCamera(message = "已停止傳送") {
    session += 1;

    clearTimeout(timer);
    timer = null;

    if (upload) {
        upload.abort();
    }

    upload = null;

    if (stream) {
        stream.getTracks().forEach(track => track.stop());
    }

    stream = null;
    video.srcObject = null;

    startButton.disabled = false;
    stopButton.disabled = true;
    facing.disabled = false;

    statusText.textContent = message;

    latestMessage = message;
}

// =====================================================
// 啟動攝影機
// =====================================================

async function startCamera() {
    if (
        !window.isSecureContext ||
        !navigator.mediaDevices?.getUserMedia
    ) {
        statusText.textContent =
            "手機開啟攝影機需要受信任的 HTTPS 連線。";
        return;
    }

    const current = ++session;

    startButton.disabled = true;
    stopButton.disabled = false;
    facing.disabled = true;

    statusText.textContent = "等待攝影機權限…";

    resetMetrics();

    try {
        const acquired =
            await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: {
                        ideal: facing.value
                    },
                    width: {
                        ideal: 640
                    },
                    height: {
                        ideal: 480
                    },
                    frameRate: {
                        ideal: 30
                    }
                },
                audio: false
            });

        if (current !== session) {
            acquired.getTracks().forEach(track => track.stop());
            return;
        }

        stream = acquired;

        acquired.getVideoTracks()[0].addEventListener(
            "ended",
            () => {
                if (current === session) {
                    stopCamera("鏡頭已中斷，請重新開始。");
                }
            }
        );

        video.srcObject = acquired;

        await video.play();

        if (current !== session) {
            return;
        }

        latestMessage = "攝影機已啟動";
        statusText.textContent = latestMessage;

        sendNext(current);

    } catch (error) {
        if (current === session) {
            stopCamera(
                "無法開啟鏡頭：" + error.message
            );
        }
    }
}

// =====================================================
// 影像擷取與橫向處理
// =====================================================

function captureFrame() {
    if (video.readyState < 2 || !video.videoWidth) {
        return false;
    }

    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;

    const isPortrait = sourceHeight > sourceWidth;

    const scale = Math.min(
        1,
        MAX_IMAGE_SIZE /
            Math.max(sourceWidth, sourceHeight)
    );

    if (isPortrait) {
        // 直向拍攝時，旋轉為橫向輸出
        canvas.width = Math.max(
            1,
            Math.round(sourceHeight * scale)
        );

        canvas.height = Math.max(
            1,
            Math.round(sourceWidth * scale)
        );

        context.save();

        context.translate(
            0,
            canvas.height
        );

        context.rotate(-Math.PI / 2);

        context.drawImage(
            video,
            0,
            0,
            canvas.height,
            canvas.width
        );

        context.restore();

    } else {
        canvas.width = Math.max(
            1,
            Math.round(sourceWidth * scale)
        );

        canvas.height = Math.max(
            1,
            Math.round(sourceHeight * scale)
        );

        context.drawImage(
            video,
            0,
            0,
            canvas.width,
            canvas.height
        );
    }

    return true;
}

// =====================================================
// JPEG 編碼
// =====================================================

function encodeJPEG() {
    return new Promise(resolve => {
        canvas.toBlob(
            resolve,
            "image/jpeg",
            JPEG_QUALITY
        );
    });
}

// =====================================================
// 上傳影像
// 一次只處理一張，避免影格排隊
// =====================================================

async function sendNext(current) {
    if (current !== session || !stream) {
        return;
    }

    const started = performance.now();

    let controller = null;
    let deadline = null;

    try {
        const ready = captureFrame();

        if (!ready) {
            latestMessage = "等待攝影機畫面…";
            return;
        }

        // 量測 JPEG 編碼時間
        const encodeStart = performance.now();

        const blob = await encodeJPEG();

        const encodeMs =
            performance.now() - encodeStart;

        if (current !== session || !stream) {
            return;
        }

        if (!blob) {
            throw new Error("JPEG 編碼失敗");
        }

        const frameKB = blob.size / 1024;

        // 上傳設定
        controller = new AbortController();
        upload = controller;

        deadline = setTimeout(
            () => controller.abort(),
            UPLOAD_TIMEOUT_MS
        );

        const uploadStart = performance.now();

        const response = await fetch("/phone_frame", {
            method: "POST",
            headers: {
                "Content-Type": "image/jpeg"
            },
            body: blob,
            cache: "no-store",
            signal: controller.signal
        });

        const uploadMs =
            performance.now() - uploadStart;

        if (!response.ok) {
            throw new Error(
                "伺服器回覆 HTTP " + response.status
            );
        }

        if (current !== session) {
            return;
        }

        // 成功統計
        successFrames++;

        totalEncodeMs += encodeMs;
        totalUploadMs += uploadMs;
        totalFrameKB += frameKB;

        latestMessage =
            `影像傳送正常 · ${canvas.width} × ${canvas.height}`;

    } catch (error) {
        if (current === session) {
            failedFrames++;

            latestMessage =
                "傳送失敗，正在重試：" +
                (
                    error.name === "AbortError"
                        ? "連線逾時"
                        : error.message
                );
        }

    } finally {
        clearTimeout(deadline);

        if (upload === controller) {
            upload = null;
        }

        if (current === session && stream) {
            updateMetrics();

            const targetFPS = Math.max(
                1,
                Number(fps.value) || 15
            );

            const interval = 1000 / targetFPS;

            const elapsed =
                performance.now() - started;

            const delay = Math.max(
                0,
                interval - elapsed
            );

            timer = setTimeout(
                () => sendNext(current),
                delay
            );
        }
    }
}

// =====================================================
// 按鈕事件
// =====================================================

startButton.addEventListener(
    "click",
    startCamera
);

stopButton.addEventListener(
    "click",
    () => stopCamera()
);

// 頁面離開時停止攝影機
window.addEventListener(
    "pagehide",
    () => stopCamera()
);

// 手機切換背景時停止傳送
document.addEventListener(
    "visibilitychange",
    () => {
        if (document.hidden) {
            stopCamera(
                "頁面已切到背景，回到此頁後請重新開始。"
            );
        }
    }
);
