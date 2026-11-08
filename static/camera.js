
"use strict";

// =====================================================
// 掌中智戲｜手機攝影機串流優化版 v3
//
// 修正：30 FPS 攝影機擷取 20 FPS 時的排程問題
//
// 保留功能：
// 1. requestVideoFrameCallback 新影格追蹤
// 2. 擷取與 HTTP 上傳分離
// 3. 最多保留一張待傳影格
// 4. 避免 HTTP 請求堆積
// 5. 手機直向影像轉橫向
// 6. 完整效能監控
// =====================================================


// =====================================================
// DOM 元件
// =====================================================

const video = document.querySelector("#camera");
const canvas = document.querySelector("#capture");

const context = canvas.getContext("2d", {
    alpha: false
});

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
const FALLBACK_INTERVAL_MS = 20;

// 避免浮點數時間誤差
const CAPTURE_TIME_TOLERANCE_MS = 0.5;


// =====================================================
// 攝影機與傳輸狀態
// =====================================================

let stream = null;
let session = 0;

let frameCallbackId = null;
let fallbackTimer = null;

let uploadController = null;

let uploading = false;
let encoding = false;

// 最多保留一張待傳 JPEG
let pendingFrame = null;

// 新版擷取排程
let nextCaptureDue = null;
let lastTargetFPS = null;

// 攝影機影格時間
let lastCameraFrameTime = null;
let lastFallbackMediaTime = -1;

let captureMode = "尚未啟動";
let latestMessage = "尚未開啟鏡頭";


// =====================================================
// 效能統計
// =====================================================

let metricsStart = 0;

let cameraFrameCount = 0;
let captureFrameCount = 0;

let cameraIntervalCount = 0;
let totalCameraInterval = 0;
let maxCameraInterval = 0;

let successFrames = 0;
let failedFrames = 0;

let totalEncodeMs = 0;
let totalUploadMs = 0;
let totalJPEGKB = 0;
let totalCaptureToResponseMs = 0;

let lastSuccessfulUploadTime = null;

let uploadIntervalCount = 0;
let totalUploadInterval = 0;
let maxUploadInterval = 0;

let replacedFrames = 0;
let skippedFrames = 0;

let encodeSamples = [];
let uploadSamples = [];


// =====================================================
// 工具函式
// =====================================================

function average(total, count) {
    return count > 0 ? total / count : 0;
}

function percentile95(values) {
    if (values.length === 0) {
        return 0;
    }

    const sorted = [...values].sort(
        (a, b) => a - b
    );

    const index = Math.min(
        sorted.length - 1,
        Math.ceil(sorted.length * 0.95) - 1
    );

    return sorted[index];
}

function getTargetFPS() {
    return Math.max(
        1,
        Number(fps.value) || 15
    );
}


// =====================================================
// 重設效能統計
// =====================================================

function resetMetrics() {
    metricsStart = performance.now();

    cameraFrameCount = 0;
    captureFrameCount = 0;

    cameraIntervalCount = 0;
    totalCameraInterval = 0;
    maxCameraInterval = 0;

    successFrames = 0;
    failedFrames = 0;

    totalEncodeMs = 0;
    totalUploadMs = 0;
    totalJPEGKB = 0;
    totalCaptureToResponseMs = 0;

    lastSuccessfulUploadTime = null;

    uploadIntervalCount = 0;
    totalUploadInterval = 0;
    maxUploadInterval = 0;

    replacedFrames = 0;
    skippedFrames = 0;

    encodeSamples = [];
    uploadSamples = [];
}


// =====================================================
// 記錄攝影機新影格
// =====================================================

function recordCameraFrame(now) {
    cameraFrameCount++;

    if (lastCameraFrameTime !== null) {
        const interval =
            now - lastCameraFrameTime;

        if (interval > 0) {
            cameraIntervalCount++;
            totalCameraInterval += interval;

            maxCameraInterval = Math.max(
                maxCameraInterval,
                interval
            );
        }
    }

    lastCameraFrameTime = now;
}


// =====================================================
// 記錄成功上傳
// =====================================================

function recordSuccessfulUpload(now) {
    successFrames++;

    if (lastSuccessfulUploadTime !== null) {
        const interval =
            now - lastSuccessfulUploadTime;

        if (interval > 0) {
            uploadIntervalCount++;
            totalUploadInterval += interval;

            maxUploadInterval = Math.max(
                maxUploadInterval,
                interval
            );
        }
    }

    lastSuccessfulUploadTime = now;
}


// =====================================================
// 更新手機畫面監控
// =====================================================

function updateMetrics() {
    const now = performance.now();
    const elapsed = now - metricsStart;

    if (elapsed < METRICS_INTERVAL_MS) {
        return;
    }

    const seconds = Math.max(
        elapsed / 1000,
        0.001
    );

    const cameraFPS =
        cameraFrameCount / seconds;

    const captureFPS =
        captureFrameCount / seconds;

    const uploadFPS =
        successFrames / seconds;

    const avgCameraInterval = average(
        totalCameraInterval,
        cameraIntervalCount
    );

    const avgUploadInterval = average(
        totalUploadInterval,
        uploadIntervalCount
    );

    const avgEncode = average(
        totalEncodeMs,
        successFrames
    );

    const avgUpload = average(
        totalUploadMs,
        successFrames
    );

    const avgJPEG = average(
        totalJPEGKB,
        successFrames
    );

    const avgCaptureToResponse = average(
        totalCaptureToResponseMs,
        successFrames
    );

    const encodeP95 =
        percentile95(encodeSamples);

    const uploadP95 =
        percentile95(uploadSamples);

    statusText.style.whiteSpace = "pre-line";

    statusText.textContent =
        `${latestMessage}\n` +
        `擷取模式：${captureMode}\n` +
        `設定 FPS：${getTargetFPS()}\n` +
        `攝影機新影格 FPS：${cameraFPS.toFixed(1)}\n` +
        `實際擷取 FPS：${captureFPS.toFixed(1)}\n` +
        `實際上傳 FPS：${uploadFPS.toFixed(1)}\n` +
        `平均攝影機影格間隔：${avgCameraInterval.toFixed(1)} ms\n` +
        `最大攝影機影格間隔：${maxCameraInterval.toFixed(1)} ms\n` +
        `平均成功上傳間隔：${avgUploadInterval.toFixed(1)} ms\n` +
        `最大成功上傳間隔：${maxUploadInterval.toFixed(1)} ms\n` +
        `JPEG 大小：${avgJPEG.toFixed(1)} KB\n` +
        `JPEG 編碼平均：${avgEncode.toFixed(1)} ms\n` +
        `JPEG 編碼 P95：${encodeP95.toFixed(1)} ms\n` +
        `上傳往返平均：${avgUpload.toFixed(1)} ms\n` +
        `上傳往返 P95：${uploadP95.toFixed(1)} ms\n` +
        `擷取至回覆平均：${avgCaptureToResponse.toFixed(1)} ms\n` +
        `待傳影格覆蓋：${replacedFrames}\n` +
        `略過影格：${skippedFrames}\n` +
        `失敗次數：${failedFrames}`;

    console.log(
        "[掌中智戲｜手機串流效能]",
        {
            captureMode,

            targetFPS: getTargetFPS(),

            cameraFPS:
                cameraFPS.toFixed(1),

            captureFPS:
                captureFPS.toFixed(1),

            uploadFPS:
                uploadFPS.toFixed(1),

            avgCameraInterval:
                avgCameraInterval.toFixed(1),

            avgUploadInterval:
                avgUploadInterval.toFixed(1),

            maxUploadInterval:
                maxUploadInterval.toFixed(1),

            avgEncode:
                avgEncode.toFixed(1),

            encodeP95:
                encodeP95.toFixed(1),

            avgUpload:
                avgUpload.toFixed(1),

            uploadP95:
                uploadP95.toFixed(1),

            replacedFrames,
            skippedFrames,
            failedFrames
        }
    );

    resetMetrics();
}


// =====================================================
// 停止攝影機
// =====================================================

function stopCamera(
    message = "已停止傳送"
) {
    session++;

    if (
        frameCallbackId !== null &&
        typeof video.cancelVideoFrameCallback ===
            "function"
    ) {
        video.cancelVideoFrameCallback(
            frameCallbackId
        );
    }

    frameCallbackId = null;

    clearTimeout(fallbackTimer);
    fallbackTimer = null;

    if (uploadController) {
        uploadController.abort();
    }

    uploadController = null;

    uploading = false;
    encoding = false;
    pendingFrame = null;

    if (stream) {
        stream.getTracks().forEach(
            track => track.stop()
        );
    }

    stream = null;
    video.srcObject = null;

    nextCaptureDue = null;
    lastTargetFPS = null;

    lastCameraFrameTime = null;
    lastFallbackMediaTime = -1;

    startButton.disabled = false;
    stopButton.disabled = true;
    facing.disabled = false;

    latestMessage = message;

    statusText.textContent = message;
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
            "手機攝影機需要受信任的 HTTPS 連線。";
        return;
    }

    const current = ++session;

    startButton.disabled = true;
    stopButton.disabled = false;
    facing.disabled = true;

    statusText.textContent =
        "等待攝影機權限…";

    nextCaptureDue = null;
    lastTargetFPS = null;

    lastCameraFrameTime = null;
    lastFallbackMediaTime = -1;

    uploading = false;
    encoding = false;
    pendingFrame = null;

    captureMode = "啟動中";

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
            acquired.getTracks().forEach(
                track => track.stop()
            );
            return;
        }

        stream = acquired;

        acquired.getVideoTracks()[0]
            .addEventListener(
                "ended",
                () => {
                    if (current === session) {
                        stopCamera(
                            "手機攝影機已中斷。"
                        );
                    }
                }
            );

        video.srcObject = acquired;

        await video.play();

        if (current !== session) {
            return;
        }

        latestMessage =
            "攝影機已啟動";

        resetMetrics();

        if (
            typeof video.requestVideoFrameCallback ===
            "function"
        ) {
            captureMode = "新影格追蹤";
            startVideoFrameTracking(current);
        } else {
            captureMode = "相容備援模式";
            startFallbackTracking(current);
        }

        statusText.textContent =
            `${latestMessage} · ${captureMode}`;

    } catch (error) {
        if (current === session) {
            stopCamera(
                "無法開啟攝影機：" +
                error.message
            );
        }
    }
}


// =====================================================
// requestVideoFrameCallback 新影格追蹤
// =====================================================

function startVideoFrameTracking(current) {
    function onVideoFrame(now, metadata) {
        if (current !== session || !stream) {
            return;
        }

        frameCallbackId =
            video.requestVideoFrameCallback(
                onVideoFrame
            );

        recordCameraFrame(now);

        tryCaptureLatestFrame(current, now);

        updateMetrics();
    }

    frameCallbackId =
        video.requestVideoFrameCallback(
            onVideoFrame
        );
}


// =====================================================
// 不支援新影格追蹤時的備援模式
// =====================================================

function startFallbackTracking(current) {
    function checkFrame() {
        if (current !== session || !stream) {
            return;
        }

        const now = performance.now();

        if (
            video.readyState >= 2 &&
            video.videoWidth > 0
        ) {
            const mediaTime =
                video.currentTime;

            if (
                mediaTime !==
                lastFallbackMediaTime
            ) {
                lastFallbackMediaTime =
                    mediaTime;

                recordCameraFrame(now);

                tryCaptureLatestFrame(
                    current,
                    now
                );
            }
        }

        updateMetrics();

        fallbackTimer = setTimeout(
            checkFrame,
            FALLBACK_INTERVAL_MS
        );
    }

    checkFrame();
}


// =====================================================
// 新版：影格擷取排程
//
// 原本做法：
// 上次擷取時間 + 50 ms
// 可能一直落在 66.7 ms 的攝影機週期
//
// 新版做法：
// 使用累積的預定擷取時間
// 讓 30 FPS 攝影機平均選出 20 FPS
//
// 可能的擷取時間：
// 0、66.7、100、166.7、200 ms...
//
// 不是要求每張都剛好間隔 50 ms
// 而是讓長時間平均接近設定 FPS
// =====================================================

function tryCaptureLatestFrame(current, now) {
    if (current !== session || !stream) {
        return;
    }

    const targetFPS = getTargetFPS();

    const targetInterval =
        1000 / targetFPS;

    // 開始時或使用者切換 FPS 時
    // 重新建立排程
    if (
        nextCaptureDue === null ||
        lastTargetFPS !== targetFPS
    ) {
        nextCaptureDue = now;
        lastTargetFPS = targetFPS;
    }

    // 還沒到預定擷取時間
    if (
        now + CAPTURE_TIME_TOLERANCE_MS <
        nextCaptureDue
    ) {
        skippedFrames++;
        return;
    }

    // 累積排程，不以實際擷取時刻重設
    nextCaptureDue += targetInterval;

    // 如果因卡頓錯過很多個週期
    // 直接跳到下一個未來時間
    // 避免之後連續追趕過時影格
    if (nextCaptureDue <= now) {
        const missedIntervals =
            Math.floor(
                (now - nextCaptureDue) /
                targetInterval
            ) + 1;

        nextCaptureDue +=
            missedIntervals * targetInterval;
    }

    // 防止同時啟動多個 JPEG 編碼
    if (encoding) {
        skippedFrames++;
        return;
    }

    encoding = true;

    prepareFrame(current, now);
}


// =====================================================
// Canvas 擷取
// =====================================================

function captureFrame() {
    if (
        video.readyState < 2 ||
        !video.videoWidth
    ) {
        return false;
    }

    const sourceWidth =
        video.videoWidth;

    const sourceHeight =
        video.videoHeight;

    const isPortrait =
        sourceHeight > sourceWidth;

    const scale = Math.min(
        1,
        MAX_IMAGE_SIZE /
            Math.max(
                sourceWidth,
                sourceHeight
            )
    );

    const targetWidth = Math.max(
        1,
        Math.round(
            (
                isPortrait
                    ? sourceHeight
                    : sourceWidth
            ) * scale
        )
    );

    const targetHeight = Math.max(
        1,
        Math.round(
            (
                isPortrait
                    ? sourceWidth
                    : sourceHeight
            ) * scale
        )
    );

    // 只有尺寸改變才重設 Canvas
    if (canvas.width !== targetWidth) {
        canvas.width = targetWidth;
    }

    if (canvas.height !== targetHeight) {
        canvas.height = targetHeight;
    }

    if (isPortrait) {
        context.save();

        context.translate(
            0,
            canvas.height
        );

        context.rotate(
            -Math.PI / 2
        );

        context.drawImage(
            video,
            0,
            0,
            canvas.height,
            canvas.width
        );

        context.restore();

    } else {
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
// 影像擷取與 JPEG 編碼
// =====================================================

async function prepareFrame(
    current,
    capturedAt
) {
    try {
        if (!captureFrame()) {
            return;
        }

        captureFrameCount++;

        const encodeStart =
            performance.now();

        const blob =
            await encodeJPEG();

        const encodeMs =
            performance.now() -
            encodeStart;

        if (
            current !== session ||
            !stream
        ) {
            return;
        }

        if (!blob) {
            throw new Error(
                "JPEG 編碼失敗"
            );
        }

        const frame = {
            blob,
            capturedAt,
            encodeMs,
            jpegKB:
                blob.size / 1024
        };

        // 新影格取代尚未上傳的舊影格
        if (pendingFrame !== null) {
            replacedFrames++;
        }

        pendingFrame = frame;

        // 若沒有上傳工作，就立即傳送
        sendPendingFrame(current);

    } catch (error) {
        if (current === session) {
            failedFrames++;

            latestMessage =
                "影像編碼失敗：" +
                error.message;
        }

    } finally {
        if (current === session) {
            encoding = false;
        }
    }
}


// =====================================================
// HTTP 上傳
//
// 同時最多一個請求
// 新影格可以在舊影格上傳期間準備
// 不排隊傳送多張舊影格
// =====================================================

async function sendPendingFrame(current) {
    if (
        current !== session ||
        !stream ||
        uploading ||
        pendingFrame === null
    ) {
        return;
    }

    uploading = true;

    try {
        while (
            current === session &&
            stream &&
            pendingFrame !== null
        ) {
            const frame = pendingFrame;

            pendingFrame = null;

            const controller =
                new AbortController();

            uploadController =
                controller;

            let deadline = null;

            try {
                deadline = setTimeout(
                    () => controller.abort(),
                    UPLOAD_TIMEOUT_MS
                );

                const uploadStart =
                    performance.now();

                const response = await fetch(
                    "/phone_frame",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "image/jpeg"
                        },

                        body: frame.blob,

                        cache: "no-store",

                        signal:
                            controller.signal
                    }
                );

                const responseAt =
                    performance.now();

                if (!response.ok) {
                    throw new Error(
                        "伺服器回覆 HTTP " +
                        response.status
                    );
                }

                if (current !== session) {
                    return;
                }

                const uploadMs =
                    responseAt - uploadStart;

                const captureToResponseMs =
                    responseAt -
                    frame.capturedAt;

                recordSuccessfulUpload(
                    responseAt
                );

                totalEncodeMs +=
                    frame.encodeMs;

                totalUploadMs +=
                    uploadMs;

                totalJPEGKB +=
                    frame.jpegKB;

                totalCaptureToResponseMs +=
                    captureToResponseMs;

                encodeSamples.push(
                    frame.encodeMs
                );

                uploadSamples.push(
                    uploadMs
                );

                latestMessage =
                    `影像傳送正常 · ` +
                    `${canvas.width} × ` +
                    `${canvas.height}`;

            } catch (error) {
                if (current === session) {
                    failedFrames++;

                    latestMessage =
                        "傳送失敗，正在重試：" +
                        (
                            error.name ===
                            "AbortError"
                                ? "連線逾時"
                                : error.message
                        );
                }

            } finally {
                clearTimeout(deadline);

                if (
                    uploadController ===
                    controller
                ) {
                    uploadController = null;
                }
            }
        }

    } finally {
        if (current === session) {
            uploading = false;

            // 避免結束瞬間漏掉新影格
            if (pendingFrame !== null) {
                sendPendingFrame(current);
            }
        }
    }
}


// =====================================================
// FPS 切換
//
// 不重新啟動攝影機
// 下一張影格重新建立擷取時間表
// =====================================================

fps.addEventListener(
    "change",
    () => {
        nextCaptureDue = null;
        lastTargetFPS = null;

        if (stream) {
            latestMessage =
                `FPS 目標已改為 ` +
                `${getTargetFPS()}`;
        }
    }
);


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


// =====================================================
// 頁面離開時停止
// =====================================================

window.addEventListener(
    "pagehide",
    () => stopCamera()
);

document.addEventListener(
    "visibilitychange",
    () => {
        if (document.hidden && stream) {
            stopCamera(
                "頁面已切到背景，請重新開始傳送。"
            );
        }
    }
);
