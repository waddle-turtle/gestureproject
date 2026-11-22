# 掌中智戲（實體皮影戲與機電控制）

以 Raspberry Pi、MediaPipe 手勢辨識、Arduino／PCA9685 與提線戲偶組成互動式皮影戲系統；Flask 提供操作舞台和手機實體戲偶直播畫面。

## 部署現況（2026-11-22，依硬體組實機回報）

- Raspberry Pi 4 使用專案 Conda 環境 `mj_env` 執行 `app.py`；`palmtheatre.service` 已設定為開機啟動，且實測 `active`。
- NetworkManager 的 `PalmTheatre-AP` 開機自動建立 2.4 GHz Wi‑Fi（SSID `PalmTheatre`），Raspberry Pi 熱點位址 `10.42.0.1/24`，採 WPA-PSK、IPv4 shared。展示不需依賴外部手機熱點或筆電提供網路。
- 操作網頁：`https://10.42.0.1:5000`；iPhone 攝影機頁：`https://10.42.0.1:5000/phone`。
- 2026-11-22 實測：筆電連接獨立熱點後可開啟舞台；iPhone 連接熱點後，經 HTTPS 憑證信任設定，實體戲偶的手機直播畫面已成功出現在舞台。
- `/puppet_stream_stats` 可用來檢查手機影像接收。先前排查時曾出現 `connected:false`、`receive_fps:0`，後續已排除 iPhone 憑證阻擋並由使用者確認舞台直播成功；**尚未提供本次最終串流 FPS 或長時間穩定性數值**。
- 啟動時 Camera 約 30 FPS、AI 約 7.4–7.6 FPS、Preview 約 17.4–18 FPS，是 2026-11-22 單段日誌觀察值，非長期平均。
- Arduino／六馬達與雙戲偶的本輪獨立熱點展示整合測試**尚未重做驗收**；不能據此宣稱全機電鏈路在本次部署已通過。

## 開啟展示

1. 為 Raspberry Pi 提供穩定電源，等待 `PalmTheatre` Wi‑Fi 出現。
2. 使用者手機或筆電加入 `PalmTheatre`（密碼由管理者另外提供，**不在 GitHub 公開**）。顯示「無網際網路」屬預期，請保持連線。
3. 在瀏覽器開啟 `https://10.42.0.1:5000`。
4. 已經完成憑證信任設定的展示用 iPhone，可開啟 `https://10.42.0.1:5000/phone` 上傳實體戲偶影像。
5. **一般訪客不應被要求安裝私人 CA 根憑證**；若要對外開放多台未知手機，應另規劃受公眾信任的 HTTPS 方案。

## 修改程式與交接

- 筆電不必是原負責人的筆電。獲授權的開發者可加入 `PalmTheatre`，用 `ssh <授權帳號>@10.42.0.1` 或 VS Code Remote-SSH 編輯 Raspberry Pi 上的程式。
- 連上 Wi‑Fi **不等於**取得 SSH 或 GitHub 寫入權限。請分配獨立帳號、SSH 公鑰及 GitHub 協作者權限，不要公開共用管理者密碼。
- 熱點預設沒有對外網際網路，開發者可在本地編輯和測試；若要 `git push`、下載套件或同步 GitHub，需另外提供網際網路。
- 正式操作與故障排除：參見 [docs/PALMTHEATRE_DEPLOYMENT.md](docs/PALMTHEATRE_DEPLOYMENT.md)。

## 安全注意

絕對不要提交 `certs/key.pem`、`rootCA-key.pem`、`server-key.pem`、Wi‑Fi 密碼、個人 SSH 金鑰或完整環境秘密。私人 CA 僅供管理者控制的展示手機使用；網站憑證預計 **2027-11-22 到期**，需提前更新。

本文件記錄的是**實機回報與交接現況**，不代表所有硬體及長時壓力情境已正式驗收。
