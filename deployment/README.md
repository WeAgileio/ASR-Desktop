# Google Drive 非同步逐字稿服務

GitHub 建置與鏡像部署見 [GHCR 指南](GHCR.md)；發布用 Compose 為 `compose.ghcr.yaml`，本機建置使用 `compose.yaml`。

首次安裝請先閱讀 [Mac mini 完整部署指南](MAC_MINI_GUIDE.md)，依序完成 OAuth 設定、Docker 啟動、兩檔驗收與 launchd 常駐；本頁保留進階設定與驗證工具說明。

同一台 Apple Silicon Mac：Docker 執行 Web/API、SQLite、Redis 與唯讀 RQ Dashboard；原生 Python scanner 掃描 Drive，單一 RQ SpawnWorker 依序下載、辨識及上傳。SQLite 僅由 API 存取。每個 RQ 子程序完成後退出，釋放模型；scanner 可獨立處理新批次。

## 準備環境

需要 Docker Compose、FFmpeg、uv 和 Python 3.11.15。保持既有 CLI `.venv` 不變，從專案根目錄執行：

```sh
uv venv .venv-service --python 3.11.15
uv pip sync deployment/requirements/service.lock --python .venv-service/bin/python
uv venv .venv-worker --python 3.11.15
uv pip sync deployment/requirements/worker-macos-arm64.lock --python .venv-worker/bin/python
```

service lock 不含 PyTorch/FunASR；worker lock 為 macOS ARM64。API Docker 使用獨立 Linux runtime。模型首次下載需要網路及額外磁碟空間。正式部署建議將程式本身也放在非同步本機目錄。

## 設定與憑證

在非 iCloud／Dropbox／OneDrive 目錄建立專用資料目錄，例如 `~/Library/Application Support/asr-service-config`，權限設為 700。

1. 複製 `env.example` 為該目錄下的 `compose.env`，各密碼/token/signing key 分別用 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 產生。設定檔權限 600。不要將它們提交或貼入紀錄。
2. 複製 `host.example.json` 為該目錄下的 `host.json`。使用實際絕對路徑。`ASR_WORKER_TOKEN_FILE` 指向單獨文字檔，其內容必須與 Compose 的 `ASR_WORKER_TOKEN` 相同；權限 600。
3. 服務帳號 JSON 留在非同步本機目錄，權限 600，設定 `GOOGLE_APPLICATION_CREDENTIALS`。金鑰不掛入 Docker、不放入任務或 Redis。
4. `ASR_WORKSPACE` 使用非同步本機工作目錄；API 的 SQLite 使用 Docker named volume，不與 Mac 分享資料庫檔案。
5. 啟用 Google Drive API。來源可為授權服務帳號讀取的 My Drive 資料夾；服務帳號模式的目的地必須位於**共用雲端硬碟**且允許服務帳號新增內容；個人 My Drive 請使用下方 OAuth 登入方式。一般「與我共用」的 My Drive 資料夾不等於共用雲端硬碟。預檢不符合時顯示 blocked。

以下命令的 `/ABSOLUTE/LOCAL` 和 `/ABSOLUTE/ASR` 都要替換為實際路徑。

## 啟動與操作

```sh
docker compose --env-file /ABSOLUTE/LOCAL/compose.env -f deployment/compose.yaml up --build -d
.venv-worker/bin/python deployment/run_host.py scanner /ABSOLUTE/LOCAL/host.json
```

另一終端啟動 worker：

```sh
.venv-worker/bin/python deployment/run_host.py worker /ABSOLUTE/LOCAL/host.json
```

- Web：`http://127.0.0.1:8090`，帳號 `admin`、`ASR_ADMIN_PASSWORD`。
- RQ Dashboard：`http://127.0.0.1:9181`，帳號 `admin`、獨立 `ASR_DASHBOARD_PASSWORD`。唯讀；重試、暫停一律從 Web 進行。
- Mac Redis：`redis://127.0.0.1:16379/0`；容器 API：`redis://redis:6379/0`。
- 所有埠僅綁 loopback。未提供遠端 TLS／多使用者權限；不要直接對外映射。Redis 不具額外密碼，僅適用受信任的單機使用者。

Web 填入來源／目的地 URL 或 ID、模型、裝置與熱詞。預設只掃一次；週期掃描最短 120 秒。遞迴列舉音訊／影片，跳過捷徑、垃圾桶、目的地與既有輸出樹。完整掃描成功後才發布任務。來源 ID、內容版本、設定與目的地共同去重；改名不重新辨識。

暫停只停止下一筆領取，當前任務會完成，scanner 仍可掃描。暫時錯誤最多自動重試三次（60、300、900 秒）；權限問題 blocked、壞檔 failed。修正後可手動重試；來源在下載期間更新時，請在批次按重新掃描，建立新內容版本任務。單筆 timeout 為 6 小時。

每個來源建立 `原檔名__來源ID前綴/版本ID/`，內含 `transcript.txt`、`subtitles.srt`、最後寫入的 `completion.json`。TXT 為未人工校訂的台灣繁體逐字稿。已辨識結果保留 checksum 與遠端 ID，補傳不重跑辨識、不建立另一套輸出。來源不修改。

## launchd

複製 `launchd/*.plist` 到 `~/Library/LaunchAgents/`，先替換所有 `/ABSOLUTE/...` 路徑，兩個 plist 都使用 `.venv-worker/bin/python`。先建立 log 目錄，再執行：

```sh
plutil -lint ~/Library/LaunchAgents/com.local.asr.worker.plist
plutil -lint ~/Library/LaunchAgents/com.local.asr.scanner.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.asr.worker.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.asr.scanner.plist
launchctl print gui/$(id -u)/com.local.asr.worker
```

停止可用 `launchctl bootout gui/$(id -u)/com.local.asr.worker`（scanner 同理）。這是使用者 LaunchAgent，需使用者登入；Docker Desktop 也須可用。Docker 晚啟動時程序以最多 30 秒退避重連。電腦睡眠會暫停處理，長音訊可使用 macOS 防睡眠設定或 `caffeinate`。不將 MPS 工作配置為系統 LaunchDaemon。程式內檔案鎖防止啟動第二組 worker；請始終使用同一 ASR_WORKSPACE。

## 容量與保留

下載前保留 `ASR_MIN_FREE_BYTES`（預設 5 GiB，最低 1 GiB）加來源大小；這是 admission 下限，長媒體的 PCM/cache 可能需要更多。磁碟不足會 blocked。

```sh
.venv-worker/bin/python deployment/run_host.py cleanup /ABSOLUTE/LOCAL/host.json
```

依 `ASR_RETENTION_DAYS`（預設 7 天）刪除已交付的 jobs 工作目錄；再次向 API 確認 completed，且有任務執行時不清理。未交付資料與共用辨識 cache 不會自動刪除。共用 cache／模型會持續佔空間，應在停機、已有備份且不需續跑後人工整理。清理不是自動排程；由管理者按需要執行。

## 一致性備份、還原、更新與回退

使用 SQLite backup API，**不要直接複製運作中的 sqlite3 主檔而漏掉 WAL**。先在 Web 暫停，等待執行中任務結束，並停止 scanner／worker：

```sh
docker compose --env-file /ABSOLUTE/LOCAL/compose.env -f deployment/compose.yaml exec -T api python -m asr_service backup --database /data/asr.sqlite3 --output /data/backup.sqlite3
docker compose --env-file /ABSOLUTE/LOCAL/compose.env -f deployment/compose.yaml cp api:/data/backup.sqlite3 /ABSOLUTE/LOCAL/backup.sqlite3
```

同時備份 workspace（包括 manifest 與 checkpoints）、外部設定與金鑰；備份放本機私有目錄或加密儲存。不要把金鑰放進一般診斷壓縮檔。

還原前保留現況備份。停止整組 Compose，讓 SQLite 無開啟中的連線；用一次性 API 容器將備份以正確 UID 放回 `/data/asr.sqlite3`，移除**該已停機資料庫**的舊 `-wal`／`-shm`。例如：

```sh
docker compose --env-file /ABSOLUTE/LOCAL/compose.env -f deployment/compose.yaml down
docker compose --env-file /ABSOLUTE/LOCAL/compose.env -f deployment/compose.yaml run --rm --no-deps -v /ABSOLUTE/LOCAL/backup.sqlite3:/restore.sqlite3:ro api python -c "import pathlib,shutil; p=pathlib.Path('/data/asr.sqlite3'); shutil.copyfile('/restore.sqlite3',p); [pathlib.Path(str(p)+s).unlink(missing_ok=True) for s in ('-wal','-shm')]"
docker compose --env-file /ABSOLUTE/LOCAL/compose.env -f deployment/compose.yaml up -d
```

還原同一份 workspace 後啟動 worker/scanner，確認任務及輸出映射，再解除暫停。Redis AOF 只保存佇列；SQLite outbox 可補送遺失佇列。不要刪除 Docker volume（`down -v` 會毀損業務資料）。舊備份不含之後新增的遠端 ID，不能保證跨越備份時間點的交付去重；還原前須先核對該期間的 Drive 成果。

更新：暫停、等任務完成、停 scanner/worker、備份，再重建 API/Dashboard 映像及同步 worker 鎖檔；確認健康後重啟 host 程序。保留舊程式／映像、鎖檔、資料庫及 workspace 備份。回退時使用相同版本的程式與資料庫備份；不可讓舊程式直接修改較新 schema。

## 驗證與目前限制

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv-service/bin/python -m unittest discover -s tests/service -v
```

`evaluation/rq_smoke.py` 使用獨立佇列連續辨識兩個指定 WAV，檢查 MPS、心跳與子程序退出。需專用 Redis：

```sh
PYTHONPATH=src:evaluation .venv-worker/bin/python evaluation/rq_smoke.py /absolute/path/sample.wav --output-dir .e2e-cache/rq-smoke/new-run
```

`evaluation/service_roundtrip.py` 僅用於專用 Docker validation stack：真 API/SQLite/RQ、假的 Drive／辨識器，注入上傳回應遺失；不作為生產入口。實際驗證證據與未完成項目見 OpenSpec 的 `runtime-validation.md`。目前 M1 Max／32GB 的短音訊結果不能替代 M4／16GB 長音訊驗收。已使用 OAuth、兩段 20 秒講座音訊完成真實 Drive 下載、MPS 辨識與 TXT／SRT／completion 回傳；這不等同於大型來源批次或 M4 長音訊驗收。

## 使用個人 My Drive：OAuth 登入

若目的地是一般 My Drive 資料夾，使用 Desktop app OAuth client，不使用服務帳號擁有新檔案。先下載桌面應用程式 OAuth client JSON 到非同步本機目錄，再以原生 worker 環境登入：

```sh
PYTHONPATH=src .venv-worker/bin/python -m asr_service.oauth --client-secrets /ABSOLUTE/LOCAL/oauth-client.json --token-file /ABSOLUTE/LOCAL/google-user-token.json
```

CLI 使用 PKCE 和 `127.0.0.1` 臨時埠接收回呼，開啟系統瀏覽器等待使用者登入同意（10 分鐘）。未成功授權不覆寫既有 token；新 token 原子儲存為 600 權限。請勿將 callback URL、驗證碼或 token 貼入紀錄。此版本遞迴讀取任意既有來源，因此申請 `https://www.googleapis.com/auth/drive`，不是僅對 Picker 選取檔案生效的 `drive.file`。

在 **worker 與 scanner 共用的 host.json** 設定：

```json
{
  "ASR_DRIVE_AUTH": "oauth",
  "ASR_GOOGLE_TOKEN_FILE": "/ABSOLUTE/LOCAL/google-user-token.json"
}
```

將這兩個欄位合併進既有設定，保留 API URL、worker token、workspace 等其他欄位。可移除該 OAuth 設定中的 `GOOGLE_APPLICATION_CREDENTIALS`。OAuth 使用者能寫入的 My Drive 或共用雲端硬碟資料夾都可作目的地；服務帳號模式仍要求共用雲端硬碟。沒有 token 或授權失效時不會自動切換到另一帳號。

每個原生程序讀取 refresh token，Google client 在記憶體自動刷新 access token；無須每個任務登入。若出現授權 blocked，重新執行上述登入命令後重試任務。切換 Google 使用者或重新授權前，先暫停領取、等待當前任務完成，再重啟 worker/scanner，避免同一批工作混用不同身份。OAuth client、token 都不掛入容器。

Google OAuth 專案若為 External + Testing，使用 Drive scope 的 refresh token 通常七天到期；需要將登入帳號加入測試使用者。長期服務應檢查 consent screen 的發布狀態與適用驗證要求，不承諾 token 永久有效。參考：[Google OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)。

OAuth 專屬測試（不登入、不連網）：

```sh
PYTHONPATH=src .venv-worker/bin/python -m unittest discover -s tests/worker -v
```

## 限定兩個檔案的真實驗收

`evaluation/drive_live.py` 會在指定目的地建立驗收子樹、複製明確指定的兩個媒體作為輸入，再透過正常 scanner、API、RQ 與 MPS worker 執行。它不掃描原始大型來源樹；會寫入真實 Drive，僅能使用已授權的檔案與目的地。

```sh
PYTHONPATH=src .venv-worker/bin/python evaluation/drive_live.py \
  --host-config /ABSOLUTE/LOCAL/host.oauth.json \
  --admin-env /ABSOLUTE/LOCAL/compose.env \
  --destination AUTHORIZED_DESTINATION_ID \
  --source-file AUTHORIZED_MEDIA_ID_1 \
  --source-file AUTHORIZED_MEDIA_ID_2 \
  --evidence-dir .e2e-cache/drive-live-new
```

保留 evidence directory 的 manifest 以沿用既有遠端 ID；不要刪掉 manifest 後對相同測試盲目重建。執行前需沒有其他等待執行的任務或待掃描批次。完成會確認兩筆序列執行、MPS 裝置與遠端 checksum，寫入 report.json。正式 M4／16GB 的長音訊驗收仍需在目標硬體另外執行，短片段成功不能替代。
