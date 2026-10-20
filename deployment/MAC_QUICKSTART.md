# Mac 原生服務：可視化管理

保留 FunASR 的 MPS 加速，使用本機管理頁操作原生 scanner／worker，不需要手寫 launchd plist。Docker Web/API、Redis、Dashboard 沿用現有部署。

這個管理頁是 `v0.1.0` 發布後新增的功能，目前需使用含以下檔案的程式碼；舊版壓縮檔沒有此入口。

## 第一次使用

1. 安裝並開啟 Docker Desktop，將專案放在非同步本機目錄，例如 `~/Projects/ASR`。
2. 在 Terminal 執行：

```sh
brew install uv ffmpeg
cd "$HOME/Projects/ASR"
bash deployment/mac-service.sh ui
```

瀏覽器會開啟 `http://127.0.0.1:9182`。帳號 `admin`，密碼是私有設定目錄中 `compose.env` 的 `ASR_ADMIN_PASSWORD`。首次啟動自動產生設定與隨機密碼，已有設定則沿用；可以在本機檢視：

```sh
open -e "$HOME/Library/Application Support/asr-service-config/compose.env"
```

不要把此檔案或密碼貼入對話、日誌或版本庫。

3. 在管理頁依序按 **安裝原生環境 → 選取 OAuth client JSON → 匯入 client → Google 登入**。安裝可能需要數分鐘；詳細套件下載進度留在終端機。Google 登入會在這台 Mac 開啟同意畫面，token 只存本機。
4. 如果 Docker stack 還沒啟動，在另一個終端機執行以下命令；GHCR 為 private 時先依 [GHCR 指南](GHCR.md) 登入。**已有 stack 的使用者沿用原先 project name 與 env，不要再開一套。**

```sh
cd "$HOME/Projects/ASR"
docker compose --project-name asr-service \
  --env-file "$HOME/Library/Application Support/asr-service-config/compose.env" \
  -f deployment/compose.ghcr.yaml up -d --pull always --no-build
```

5. 在管理頁按 **啟動服務**，再開啟任務頁確認 scanner／worker 心跳，依 [兩檔驗收步驟](MAC_MINI_GUIDE.md#6-用兩個檔案驗收) 驗證。

Docker 前台可在 Docker Desktop 查看容器啟停；原生程序用這個管理頁；佇列細節用 RQ Dashboard。管理頁不需要將 Docker socket 暴露給容器。

## 管理頁可以做什麼

| 功能 | 行為 |
| --- | --- |
| 安裝原生環境 | 建立隔離 Python 環境、同步 worker lock、產生 scanner／worker LaunchAgent |
| 啟動服務 | 檢查 API 與憑證檔案後載入 launchd；已有服務不重複載入 |
| 安全停止 | 暫停下一筆領取；若有任務執行中則保留服務，等完成後再按一次 |
| 暫停／恢復領取 | 保留目前任務，控制是否開始下一筆 |
| 同步依賴並重啟 | 安全停止、同步目前程式碼的依賴、啟動服務；最後需手動恢復領取 |
| Google 登入 | 透過桌面 OAuth client 重新授權；需先停止原生程序 |
| 儲存設定 | 修改本機 API／Redis 位址、保留天數、最低可用空間；需先停止原生程序 |
| 本機日誌 | 查看 scanner／worker 最近的 stderr 日誌 |
| 任務頁／RQ Dashboard | 開啟既有前台查看任務與心跳、佇列 |

「已載入」表示 launchd 已載入，不等於 worker 已連線；真實心跳以任務頁為準。「已儲存 OAuth 授權」也不代表 token 尚未過期。

管理頁僅綁 `127.0.0.1`，有管理密碼與 CSRF 檢查，不開放區網。管理頁需保持終端機運行；關閉它不會停止已註冊的 scanner／worker。下次只要再執行 `bash deployment/mac-service.sh ui`。原生 LaunchAgent 在使用者登入後啟動；Docker Desktop 仍須運行，睡眠時會暫停處理。

## 更新與既有環境

「同步依賴並重啟」**不會執行 Git、取得新版本、更新 Docker 或搬動資料**。先按完整指南備份並取得對應版本的程式碼，再用此按鈕同步；它不會自動解除暫停。

預設沿用 `~/Library/Application Support/asr-service-config/host.json`；沒有時會使用同目錄的 `host.oauth.json`。若沿用舊設定，請確認同目錄有對應的 `compose.env`（管理頁需用它的 admin 密碼與 Dashboard 埠），API／Redis 位址及 worker token 也要與既有 stack 一致。不要重新產生密碼。

自訂路徑：

```sh
bash deployment/mac-service.sh \
  --config-dir "/absolute/local/config" \
  --host-config "/absolute/local/config/host.oauth.json" ui
```

若已安裝同名但不同路徑／日誌設定的 LaunchAgent，工具會拒絕覆寫，避免誤改其他部署。先依原部署流程停止並保留舊 plist，再統一配置；不要同時啟動兩份原生 worker。更新失敗時服務會保持暫停，修正後重新安裝／啟動即可。

設定頁只更改原生程序的連線位址，不會修改 Docker 埠或管理密碼。保留天數作用於手動 cleanup；目前未新增自動清理排程。

也可以使用命令列：

```sh
bash deployment/mac-service.sh status
bash deployment/mac-service.sh stop
bash deployment/mac-service.sh start
bash deployment/mac-service.sh resume
bash deployment/mac-service.sh logs worker
```

完整備份、還原、容量限制與 M4／16GB 驗收說明，見 [Mac mini 部署指南](MAC_MINI_GUIDE.md)。
