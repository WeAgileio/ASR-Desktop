# Mac mini 部署指南

希望減少終端機操作？先看 [Mac 可視化管理快速指南](MAC_QUICKSTART.md)，可用瀏覽器安裝、授權、啟停與設定原生服務。

適用：Apple Silicon Mac mini、16GB 記憶體，同一台機器執行 Docker 前台與 macOS 原生 FunASR worker，一次處理一個任務。本指南採用 **Google 使用者 OAuth**，可將結果寫入該使用者有寫入權限的 My Drive 資料夾。

目前已有 M1 Max／32GB 的兩段 20 秒音訊端到端驗證；**M4／16GB 長音訊尚未完成驗收**。先完成第 6 節的小批次測試，再開始正式批次。

## 1. 架構與資料放置

```text
瀏覽器 → Docker Web/API → SQLite（Docker volume）
                 │
                 └→ Redis / RQ（Docker volume）
                           ↓
Google Drive ← macOS 原生 worker（單工、FunASR / MPS）
      ↑                    │
      └─ 原生 scanner ─────┴→ API 更新任務狀態

Docker 另提供唯讀 RQ Dashboard
launchd 管理原生 scanner 與 worker
```

SQLite 只有 API 存取；worker 透過 API 更新狀態。Google 憑證放在 Mac 本機，不放進 Docker、Redis 或程式碼。

建議配置：

| 用途 | 路徑 |
| --- | --- |
| 專案程式 | `~/Projects/ASR` |
| 密碼、OAuth、host 設定 | `~/Library/Application Support/asr-service-config` |
| 工作檔、checkpoint | `~/Library/Application Support/asr-service` |
| 原生程序日誌 | 上述設定目錄的 `logs/` |
| SQLite、Redis | Docker named volumes |

程式、憑證與工作目錄請放在本機非同步目錄，避免 iCloud、Dropbox 或 OneDrive。將專案複製到目標 Mac 時，不複製舊 `.venv*`、快取或憑證；Python 環境在新機重建。若要保留既有任務紀錄，先看第 9 節，不能只搬程式。

## 2. 安裝環境

先安裝並啟動 Apple Silicon 版 Docker Desktop，確認終端機可使用 Homebrew。以下命令在 Mac 的 Terminal 執行：

```sh
brew install uv ffmpeg
docker info
docker compose version
uname -m
ffmpeg -version
```

`uname -m` 應為 `arm64`。不要在 Rosetta 的 x86_64 環境安裝 worker。

以下路徑以新機為例，請先將專案放到對應位置。**每開一個新終端機，都先執行這個設定區塊**；後續命令會用到其中的變數與函式。

```sh
export ASR_APP="$HOME/Projects/ASR"
export ASR_CONFIG="$HOME/Library/Application Support/asr-service-config"
export ASR_DATA="$HOME/Library/Application Support/asr-service"

asr_compose() {
  docker compose --project-name asr-service \
    --env-file "$ASR_CONFIG/compose.env" \
    -f "$ASR_APP/deployment/compose.yaml" "$@"
}

cd "$ASR_APP"
```

建立原生 worker 環境：

```sh
uv python install 3.11.15
uv venv "$ASR_APP/.venv-worker" --python 3.11.15
uv pip sync "$ASR_APP/deployment/requirements/worker-macos-arm64.lock" \
  --python "$ASR_APP/.venv-worker/bin/python"

"$ASR_APP/.venv-worker/bin/python" -c 'import platform, torch; print("architecture:", platform.machine()); print("MPS available:", torch.backends.mps.is_available())'
```

預期為 `arm64`、`MPS available: True`。API 的依賴由 Docker 建置；一般部署不用額外建立 `.venv-service`，也不用修改原本 CLI 的 `.venv`。模型首次下載需要網路與額外磁碟空間。

## 3. 建立本機設定

以下區塊用於**全新部署**：產生四組獨立密碼，並確保 API 與 worker 使用同一個 worker token。已有設定時會停止，避免意外換掉密碼。

```sh
"$ASR_APP/.venv-worker/bin/python" - <<'PY'
import json
import os
from pathlib import Path
import secrets

os.umask(0o077)
config = Path(os.environ["ASR_CONFIG"])
data = Path(os.environ["ASR_DATA"])
for directory in (config, data, config / "logs"):
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
paths = [config / name for name in ("compose.env", "worker-token.txt", "host.json")]
if any(path.exists() for path in paths):
    raise SystemExit("已有設定：請保留並檢查，勿重新初始化。")
values = {key: secrets.token_urlsafe(32) for key in (
    "ASR_ADMIN_PASSWORD", "ASR_WORKER_TOKEN", "ASR_SIGNING_KEY", "ASR_DASHBOARD_PASSWORD"
)}
values.update(ASR_WEB_PORT="8090", ASR_REDIS_PORT="16379", ASR_DASHBOARD_PORT="9181")
host = {
    "ASR_API_URL": "http://127.0.0.1:8090",
    "ASR_REDIS_URL": "redis://127.0.0.1:16379/0",
    "ASR_WORKER_TOKEN_FILE": str(config / "worker-token.txt"),
    "ASR_WORKSPACE": str(data),
    "ASR_DRIVE_AUTH": "oauth",
    "ASR_GOOGLE_TOKEN_FILE": str(config / "google-user-token.json"),
    "ASR_RETENTION_DAYS": "7",
    "ASR_MIN_FREE_BYTES": "5368709120",
}
contents = [
    "".join(f"{key}={value}\n" for key, value in values.items()),
    values["ASR_WORKER_TOKEN"] + "\n",
    json.dumps(host, ensure_ascii=False, indent=2) + "\n",
]
for path, content in zip(paths, contents):
    with path.open("x") as stream:
        stream.write(content)
    path.chmod(0o600)
print("設定已建立；密碼未輸出。")
PY
```

需要查看 Web 密碼時，可在本機開啟設定檔：

```sh
open -e "$ASR_CONFIG/compose.env"
```

不要把這個檔案貼入日誌、對話或提交到版本庫。變更 worker token 時，`compose.env` 與 `worker-token.txt` 必須同步更新。

## 4. Google Drive 授權

在 Google Cloud 專案啟用 Google Drive API，設定 OAuth 同意畫面，建立 **Desktop app／桌面應用程式** OAuth client。若是 External + Testing，把實際登入的 Google 帳號加入測試使用者。

下載 client JSON，將它複製到 `$ASR_CONFIG/oauth-client.json`，再執行：

```sh
chmod 600 "$ASR_CONFIG/oauth-client.json"
PYTHONPATH="$ASR_APP/src" "$ASR_APP/.venv-worker/bin/python" \
  -m asr_service.oauth \
  --client-secrets "$ASR_CONFIG/oauth-client.json" \
  --token-file "$ASR_CONFIG/google-user-token.json"
```

瀏覽器會開啟登入頁，請用**可以讀來源、寫目的地的 Google 使用者**同意授權。CLI 等待最多 10 分鐘，透過本機臨時埠接收回呼，成功後儲存權限為 `600` 的 token。不要複製驗證碼、callback URL 或 token 到對話中。

對方需要把來源資料夾分享給這個 OAuth 使用者，目的地則授予可新增檔案的權限。**只分享給服務帳號，不代表 OAuth 使用者也有權限。**

目前程式需要遞迴讀取既有資料夾，使用完整 Drive scope。External + Testing 的 refresh token 在此 scope 下通常七天到期；正式長期使用前，應確認同意畫面的發布狀態與適用的驗證要求。參考 [Google OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)。

若目的地位於 Workspace 的「共用雲端硬碟」，也可以改用服務帳號；設定方式見 [進階部署說明](README.md#設定與憑證)。一般 My Drive 的「與我共用」資料夾不等於共用雲端硬碟，本指南預設使用 OAuth。

## 5. 啟動 Docker 與前景程序

本節使用本機建置。若要由 GitHub Actions 建置並從 GHCR 拉取鏡像，請改用 [GHCR 部署流程](GHCR.md) 的 Compose 函式與啟動命令；其餘 OAuth、原生 worker 與驗收步驟相同。

```sh
asr_compose up --build -d
asr_compose ps
curl --fail http://127.0.0.1:8090/health
```

確認 API 與 Redis 健康後，開兩個終端機，各自先執行第 2 節的環境變數區塊。

終端機 A：

```sh
"$ASR_APP/.venv-worker/bin/python" "$ASR_APP/deployment/run_host.py" \
  scanner "$ASR_CONFIG/host.json"
```

終端機 B：

```sh
"$ASR_APP/.venv-worker/bin/python" "$ASR_APP/deployment/run_host.py" \
  worker "$ASR_CONFIG/host.json"
```

| 入口 | 帳號 | 密碼來源 |
| --- | --- | --- |
| [Web 任務頁](http://127.0.0.1:8090) | `admin` | `ASR_ADMIN_PASSWORD` |
| [RQ Dashboard](http://127.0.0.1:9181) | `admin` | `ASR_DASHBOARD_PASSWORD` |

Dashboard 為唯讀；建立、暫停與重試任務請使用 Web。原生程序連到 `redis://127.0.0.1:16379/0`；容器 API 使用 Docker 內部的 Redis 位址。

所有入口僅綁本機 loopback，這份配置適用本機操作；沒有遠端 TLS 或多使用者權限控制。若要讓其他電腦存取，需要另行設計存取方式。

若埠被占用，先確認是否已有測試 stack。可調整 `compose.env` 三個埠，但 Web、Redis 的改動也必須同步到 `host.json`。固定使用同一個 Compose project name，否則會連到另一組資料卷，看起來像任務消失。

## 6. 用兩個檔案驗收

先在 Drive 建立小型測試資料夾，放兩個**確定有語音**的音訊檔；輸出使用另一個資料夾，例如：

```text
部署驗收/
├── input/      ← 只有兩個音訊
└── output/     ← 指定為目的地
```

在 Web 建立批次，輸入這兩個資料夾 URL 或 ID，選擇模型、MPS 裝置，先使用單次掃描。確認：

- scanner 與 worker 在線，掃描只產生預期的兩筆任務。
- 第一筆完成下載、辨識與上傳後，第二筆才開始執行。
- 兩筆最終都是 `completed`，Web 可開啟對應 Drive 成果。
- 各結果包含 `transcript.txt`、`subtitles.srt`、最後寫入的 `completion.json`；內容與聲音大致相符。
- 相同設定重新掃描，不重複建立同版本任務。

成果結構為 `原檔名__來源ID前綴/版本ID/`。TXT 為未人工校訂的台灣繁體逐字稿；原始來源檔案不修改。

接著在 M4／16GB 上，用一個符合實際長度的長音訊測試，再加一個短音訊排在後面。記錄耗時、記憶體壓力、swap、剩餘磁碟空間與輸出完整性；確認長任務結束後仍能繼續下一筆。不要用兩段短音訊的成功推論長音訊一定能跑完。

先不要把大型來源根目錄設成測試來源：scanner 會遞迴掃描，可能一次建立大量任務。

## 7. 改成 launchd 常駐

前景測試通過後，在 Web 暫停領取，等待當前任務結束，再對兩個前景程序按 `Ctrl-C`。以下步驟安裝使用者 LaunchAgent；需登入該 Mac 使用者後才會啟動。

由專案模板產生 plist，避免手動替換含空白路徑出錯。若已有同名 plist，會停止，請先確認既有設定。

```sh
"$ASR_APP/.venv-worker/bin/python" - <<'PY'
import os
from pathlib import Path
import plistlib

app = Path(os.environ["ASR_APP"])
config = Path(os.environ["ASR_CONFIG"])
agents = Path.home() / "Library/LaunchAgents"
agents.mkdir(parents=True, exist_ok=True)
(config / "logs").mkdir(parents=True, exist_ok=True)
for role in ("scanner", "worker"):
    if (agents / f"com.local.asr.{role}.plist").exists():
        raise SystemExit(f"已有 {role} plist，請先檢查既有設定。")
for role in ("scanner", "worker"):
    name = f"com.local.asr.{role}.plist"
    with (app / "deployment/launchd" / name).open("rb") as stream:
        spec = plistlib.load(stream)
    spec["ProgramArguments"] = [str(app / ".venv-worker/bin/python"),
        str(app / "deployment/run_host.py"), role, str(config / "host.json")]
    spec["EnvironmentVariables"]["PYTHONPATH"] = str(app / "src")
    spec["StandardOutPath"] = str(config / "logs" / f"{role}.log")
    spec["StandardErrorPath"] = str(config / "logs" / f"{role}-error.log")
    with (agents / name).open("xb") as stream:
        plistlib.dump(spec, stream)
PY

plutil -lint "$HOME/Library/LaunchAgents/com.local.asr.scanner.plist"
plutil -lint "$HOME/Library/LaunchAgents/com.local.asr.worker.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.local.asr.scanner.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.local.asr.worker.plist"
launchctl print "gui/$(id -u)/com.local.asr.worker"
```

確認 Web 顯示程序在線後解除暫停。Docker Desktop 也要設定在登入時啟動；程序會在 Docker 尚未就緒時重連。Mac 睡眠會停止處理，需依長任務使用情境設定防睡眠。

worker 與 scanner 必須共用同一個 `host.json` 與 workspace。不要另開第二組 worker；程序內有單機鎖。LaunchAgent 設定 `KeepAlive`，要停止服務請用下一節的 `bootout`，不要只殺程序。

## 8. 日常操作與排錯

查看日誌：

```sh
asr_compose logs --tail=100 api
asr_compose logs --tail=100 redis
tail -n 100 "$ASR_CONFIG/logs/worker-error.log"
tail -n 100 "$ASR_CONFIG/logs/scanner-error.log"
```

安全停止：先在 Web 暫停，等待當前任務結束，再執行：

```sh
launchctl bootout "gui/$(id -u)/com.local.asr.scanner"
launchctl bootout "gui/$(id -u)/com.local.asr.worker"
asr_compose stop
```

重新啟動：`asr_compose up -d`，接著重新執行第 7 節的兩個 `launchctl bootstrap` 命令，最後在 Web 解除暫停。不需重新產生設定或 plist。

| 現象 | 檢查方向 |
| --- | --- |
| Web 開不了 | Docker 是否啟動、`asr_compose ps`、埠是否衝突 |
| worker 離線 | launchd 日誌、API／Redis URL、worker token 是否一致 |
| 任務一直 queued | 是否暫停、worker 是否在線、是否有長任務執行中 |
| Drive 權限 blocked | OAuth 登入帳號是否有來源讀取與目的地新增權限 |
| `invalid_grant`／授權失效 | 暫停並等任務結束，重新執行第 4 節授權，再重啟原生程序與重試 |
| 服務帳號不能上傳 | 目的地是否真的是共用雲端硬碟；My Drive 請採 OAuth |
| 磁碟不足 blocked | 清理已交付工作檔，確認空間足夠後重試 |
| 辨識没有結果 | 先試聽來源，檢查是否全靜音、壞檔或模型錯誤 |
| MPS 不可用 | 原生 arm64 Python、PyTorch 環境與 macOS 支援情況 |

暫停只停止下一筆任務，scanner 仍可掃描。暫時錯誤最多自動重試三次，間隔為 60、300、900 秒；單筆 timeout 為 6 小時。來源內容更新時，重新掃描建立新版本任務。

手動清理已完成且超過保留期限的本機 jobs：

```sh
"$ASR_APP/.venv-worker/bin/python" "$ASR_APP/deployment/run_host.py" \
  cleanup "$ASR_CONFIG/host.json"
```

預設保留 7 天；不清理未交付資料或共用模型／辨識快取，也沒有自動清理排程。預設空間門檻是 5 GiB 加來源大小，**並非整個長音訊任務的最高空間需求**。

## 9. 備份、更新與搬機

先在 Web 暫停、等執行中任務完成、停止 scanner／worker；保留 Docker API 運作以建立一致性 SQLite 備份：

```sh
export ASR_BACKUP="$HOME/asr-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ASR_BACKUP"
chmod 700 "$ASR_BACKUP"
asr_compose exec -T api python -m asr_service backup \
  --database /data/asr.sqlite3 --output /data/backup.sqlite3
asr_compose cp api:/data/backup.sqlite3 "$ASR_BACKUP/asr.sqlite3"
```

再備份 workspace、設定目錄，以及要回復的程式版本／鎖檔。設定目錄含密碼與 Google token，備份須放私有或加密儲存。不要直接複製運作中的 SQLite 主檔而漏掉 WAL。

更新時，先完成上述備份，再更新程式、以鎖檔同步 worker 環境、執行 `asr_compose up --build -d`，確認健康後啟動 scanner／worker。回退須使用相容版本的程式、資料庫與 workspace。

搬到另一台 Mac：重建 Python 環境，還原相同時間點的 SQLite 與 workspace，修改 host 設定及 plist 的絕對路徑。OAuth 可在新機重新授權；如果沿用設定，worker token 必須與新機 Compose 一致。Redis 佇列可由 SQLite outbox 補送，但仍須核對還原時間點前後的任務與 Drive 成果。

**不要執行 `docker compose down -v`**；這會刪除資料卷。還原備份前先保留現況，再依 [一致性備份、還原、更新與回退](README.md#一致性備份還原更新與回退) 操作。舊備份不含後來建立的遠端 ID，不能保證跨越備份時間點的交付去重。

## 10. 本專案先前驗收環境對照

以下為先前測試配置，方便辨識既有環境，並非新機預設，也不代表目前仍在運行：

| 項目 | 先前測試值 | 本指南新部署 |
| --- | --- | --- |
| Compose project | `asr-service-validation-2` | `asr-service` |
| Web 埠 | `18090` | `8090` |
| Redis 埠 | `16379` | `16379` |
| Dashboard 埠 | `19181` | `9181` |
| host 設定檔名 | `host.oauth.json` | `host.json` |

兩組 Redis 埠相同，不可在同一台機器直接同時啟動。先前測試 env 位於暫存目錄，正式部署應改用持久的私有設定目錄。操作既有 stack 時，必須使用它原本的 project name 與 env；不要套用本指南的全新初始化步驟。

目前使用者指定的 [來源資料夾](https://drive.google.com/drive/folders/1AxATCccneu8RQ3lcPlJzA2wlSGlTCTam) 與 [輸出資料夾](https://drive.google.com/drive/folders/1nTmsohSnxRdTbrUGjkl-KJSW5rMg85dD) 可供後續正式設定參考；部署驗收仍應先使用只有兩個音訊的獨立 input 資料夾。

更多測試工具、受限兩檔真實驗收與實作限制，見 [進階部署與驗證說明](README.md)。
