"use strict";
const video = document.querySelector("#camera");
const canvas = document.querySelector("#capture");
const context = canvas.getContext("2d", {alpha: false});
const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const facing = document.querySelector("#facing");
const fps = document.querySelector("#fps");
const statusText = document.querySelector("#status");
let stream = null;
let session = 0;
let upload = null;
let timer = null;

function stopCamera(message = "已停止傳送") {
  session += 1; // Invalidate callbacks from a previous start, including pending toBlob.
  clearTimeout(timer);
  if (upload) upload.abort();
  upload = null;
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null;
  video.srcObject = null;
  startButton.disabled = false;
  stopButton.disabled = true;
  facing.disabled = false;
  statusText.textContent = message;
}

async function startCamera() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    statusText.textContent = "手機開鏡頭需要受信任的 HTTPS。請依 README 設定憑證，不能使用 http://樹莓派IP。";
    return;
  }
  const current = ++session;
  startButton.disabled = true;
  stopButton.disabled = false;
  facing.disabled = true;
  statusText.textContent = "等待攝影機權限…";
  try {
    const acquired = await navigator.mediaDevices.getUserMedia({
      video: {facingMode: {ideal: facing.value}, width: {ideal: 640}, height: {ideal: 480}},
      audio: false
    });
    if (current !== session) {
      acquired.getTracks().forEach(track => track.stop());
      return;
    }
    stream = acquired;
    acquired.getVideoTracks()[0].addEventListener("ended", () => {
      if (current === session) stopCamera("鏡頭已中斷，請重新開始。");
    });
    video.srcObject = acquired;
    await video.play();
    if (current === session) sendNext(current);
  } catch (error) {
    if (current === session) stopCamera("無法開啟鏡頭：" + error.message);
  }
}

async function sendNext(current) {
  if (current !== session || !stream) return;
  const started = performance.now();
  let controller = null;
  let deadline = null;
  try {
    if (video.readyState < 2 || !video.videoWidth) return;


    // =====================================================
// 輸出固定以橫向為主
// =====================================================

const sourceWidth = video.videoWidth;
const sourceHeight = video.videoHeight;

const isPortrait = sourceHeight > sourceWidth;

// 最長邊先限制在 640，降低網路負擔
const scale = Math.min(
    1,
    480 / Math.max(sourceWidth, sourceHeight)
);

if (isPortrait) {

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


const blob = await new Promise(resolve =>
    canvas.toBlob(
        resolve,
        "image/jpeg",
        0.50
    )
);

    if (current !== session || !stream) return;
    if (!blob) throw new Error("JPEG 編碼失敗");
    controller = new AbortController();
    upload = controller;
    deadline = setTimeout(() => controller.abort(), 5000);
    const response = await fetch("/phone_frame", {
      method: "POST", headers: {"Content-Type": "image/jpeg"},
      body: blob, cache: "no-store", signal: controller.signal
    });
    if (!response.ok) throw new Error("伺服器回覆 HTTP " + response.status);
    if (current === session) statusText.textContent = "影像已傳送 · " + canvas.width + " × " + canvas.height;
  } catch (error) {
    if (current === session) statusText.textContent = "傳送失敗，正在重試：" + (error.name === "AbortError" ? "連線逾時" : error.message);
  } finally {
    clearTimeout(deadline);
    if (upload === controller) upload = null;
    // Only one frame can be in flight per session: slow links cannot build a queue.
    if (current === session && stream) {
      const delay = Math.max(0, 1000 / Number(fps.value) - (performance.now() - started));
      timer = setTimeout(() => sendNext(current), delay);
    }
  }
}

startButton.addEventListener("click", startCamera);
stopButton.addEventListener("click", () => stopCamera());
window.addEventListener("pagehide", () => stopCamera());
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopCamera("頁面已切到背景；回到此頁後請按開始傳送。");
});
