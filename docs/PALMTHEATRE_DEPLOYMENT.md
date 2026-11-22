# PalmTheatre 獨立網路與 iPhone 直播部署交接

更新：2026-11-22；環境：Raspberry Pi 4／NetworkManager／Flask HTTPS／Conda `mj_env`。

## 1. 現場架構

```text
CSI 攝影機 -> Raspberry Pi / app.py / MediaPipe -> （既有）USB Serial -> Arduino -> PCA9685 -> 伺服馬達／雙戲偶
                                               |
                           Flask HTTPS :5000 <-+-> 操作網頁／舞台
                                               ^
iPhone /phone -> JPEG POST /phone_frame --------+-> puppet_frame -> /puppet_video_feed
       （兩裝置都加入 PalmTheatre Wi-Fi，Pi: 10.42.0.1/24）
```

iPhone 直播不等於 Arduino 控制。2026-11-22 已確認手機影像成功出現在舞台；本輪未重新量測馬達整合。

## 2. 已驗證的部署設定

| 元件 | 設定／指令 | 2026-11-22 觀察 |
|---|---|---|
| NetworkManager 連線 | `PalmTheatre-AP` | `802-11-wireless.mode=ap`，`connection.autoconnect=yes`，priority `100` |
| 展示 Wi-Fi | SSID `PalmTheatre` | IPv4 shared，`10.42.0.1/24`，2.4 GHz |
| 原開發網路 | `netplan-wlan0-seaturtle` | 原設定仍保留，priority `0`；網路切換可能中斷 SSH |
| 專題服務 | `palmtheatre.service` | `enabled`、`active` |
| Flask HTTPS | `https://10.42.0.1:5000` | `/state` HTTP 200 |
| HTTPS 憑證 | `~/gesture_project/certs/cert.pem`、`key.pem` | SAN 有 IP `10.42.0.1`，到期 2027-11-22 |
| 臨時 8 分鐘回切 | `palmtheatre-boot-rollback.timer` | 使用者曾確認已停用；部署時仍應重新查詢 |

這裡的網路名稱、路徑及系統命令是**部署紀錄，不含密碼或私鑰**。

## 3. 使用者操作流程

1. 給 Raspberry Pi 供電；等 `PalmTheatre` SSID 出現。
2. 筆電／手機加入 SSID；若系統提示沒有網際網路，仍保持連接。
3. 網頁：`https://10.42.0.1:5000`；iPhone 直播：`https://10.42.0.1:5000/phone`。
4. 直播診斷：`https://10.42.0.1:5000/puppet_stream_stats`；收到影像時應有 `connected:true`、`receive_fps > 0`。
5. iPhone Safari 必須先信任網站 HTTPS 所屬 CA，且攝影機頁面需取得攝影機權限。現有私人 CA 只適合受管理的測試裝置。

## 4. 維護與遠端開發

透過 PalmTheatre SSH：`ssh <授權帳號>@10.42.0.1`；也可設 VS Code Remote-SSH。主機 `pipi.local` 在 Windows 或切換網路後不保證能解析，請優先使用固定 IP。

在 Pi 上查詢（唯讀）：

```bash
nmcli -g GENERAL.CONNECTION device show wlan0
nmcli -g connection.autoconnect,connection.autoconnect-priority connection show PalmTheatre-AP
systemctl is-enabled palmtheatre.service
systemctl is-active palmtheatre.service
systemctl is-enabled palmtheatre-boot-rollback.timer
systemctl is-active palmtheatre-boot-rollback.timer
curl -ks https://127.0.0.1:5000/puppet_stream_stats
```

開發者可在 PalmTheatre 的 LAN 上編輯程式，但 AP 無外部網際網路：GitHub push/pull 與套件下載通常需另接可上網的網路。不要在多人共用的展示 Wi-Fi 上直接共享管理員帳密；建議各人獨立 Linux 帳號與 SSH key、限制 sudo 權限。

## 5. HTTPS 憑證與備份

- 舊版 HTTPS 憑證備份：`~/project_backups/https_before_palmtheatre/`。
- 專用 CA 與新憑證產生資料夾：`~/palmtheatre_tls/`。
- 伺服器目前使用：`~/gesture_project/certs/cert.pem` 與 `key.pem`。
- 新憑證 SAN：`pipi.local`、`localhost`、`10.42.0.1`、`172.20.10.11`、`127.0.0.1`；OpenSSL 在 2026-11-22 驗證 `server-cert.pem: OK`，且 Flask 提供的實際憑證亦包含新 IP。
- 站台憑證到期：**2027-11-22**。公開 CA 憑證可傳給受控 iPhone；**CA 私鑰與伺服器私鑰絕不可分享或上傳**。
- iPhone 完成 CA 描述檔安裝後，還要至「設定 → 一般 → 關於本機 → 憑證信任設定」啟用完整信任；只允許在了解風險的自有／受管理設備進行。
- 使用私人 CA 有額外信任風險，對外公開展示／陌生訪客手機應另規劃公開可信任的 HTTPS 方案。

## 6. 已實測與尚待驗收

2026-11-22：獨立 AP 開機自動出現、筆電開網頁、SSH 以 10.42.0.1 登入、Flask HTTPS /state 200、iPhone 直播成功出現在主舞台。偵錯期間樹莓派日誌顯示 Camera 約 30 FPS、AI 約 7.4–7.6 FPS、Preview 約 17.4–18 FPS；不代表長期平均。

待驗證：多人同時連線、長時間穩定性、更新後手機直播 FPS、開機無人看守穩定性、電源和馬達控制聯動、雙角色實體連續動作及劇本完整演出。不要把此前 v2.2 的手機短時 26 FPS 當成本次部署實測數字。

## 7. 常見問題

- **手機顯示「連線不是私人連線」**：檢查 SAN 是否包含 `10.42.0.1`，以及 iPhone 是否安裝並信任對應 CA。勿用略過警告代替正式部署。
- **手機有相機預覽，舞台卻無影像**：先查 `/puppet_stream_stats`；若 `receive_fps=0`，先排查手機是否真的進入直播頁／有成功 POST `/phone_frame`。HTTP 204 是成功接收。
- **筆電切回另一 Wi-Fi 後無法登入**：兩端須處於同一可互通網路；使用 `10.42.0.1`，勿假設 `pipi.local` 一定可解析。
- **熱點出現但無法重新連線**：換裝置排查，使用有線／本機主控台確認 `nmcli`；不要在沒有回復手段時切換 AP。
- **網頁可用但 GitHub 不能 push**：本地 AP 沒外部網際網路；切換有網際網路的環境，且確認有 GitHub repository write 權限。
