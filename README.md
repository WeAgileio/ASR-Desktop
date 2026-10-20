# ASR-Desktop

適用於 Apple Silicon Mac 的本機語音轉文字工具。將錄好的音訊或影片匯入桌面 App，即可批次產生逐字稿與 SRT 字幕；也能透過 CLI 提交、追蹤及管理同一批任務。

ASR-Desktop 使用 SwiftUI 原生介面與 FunASR 推論核心，支援 Fun-ASR-Nano、Paraformer 兩種模型。模型下載完成後，轉錄使用本機資產執行，音訊不需上傳至雲端辨識服務。完整 App 內含 Python runtime、FFmpeg 與 FFprobe，日常使用不需另裝 Python、Homebrew、Redis 或 Docker。

> **目前為開發版。** 目標平台是 Apple Silicon／macOS 14 以上，現有實測環境為 Apple M1 Max／macOS 26.6.2。完整 GUI、長錄音品質與資源、乾淨 Mac／最低系統版本、正式簽署及公證驗收仍待完成。既有證據與限制見 [VALIDATION.md](desktop/VALIDATION.md)。

[操作說明](desktop/USAGE.md) · [模型管理](desktop/MODELS.md) · [CPU／GPU 政策](desktop/DEVICE-POLICY.md) · [驗收紀錄](desktop/VALIDATION.md) · [GitHub 儲存庫](https://github.com/WeAgileio/ASR-Desktop)

## 主要功能

- **桌面操作與 CLI 共用狀態**：使用相同的背景服務、任務紀錄、設定與模型儲存空間。
- **批次匯入**：選取或拖入音訊、影片及資料夾，可選擇包含子資料夾；提交前預覽有效檔案與輸出位置。
- **逐字稿與字幕**：預設輸出台灣繁體 TXT、SRT，可改為簡體或保留原文，另可匯出原始辨識結果 JSON。
- **任務佇列**：逐檔轉錄，支援暫停、恢復、取消及重試；關閉視窗或 CLI 後，背景工作仍會繼續。
- **模型下載與修復**：顯示下載進度與空間需求，驗證固定版本及 SHA-256，支援符合條件的中斷續傳。
- **CPU／GPU 選擇**：提供自動、CPU 與 Apple GPU（MPS）模式，以及使用指定樣本的 CPU／GPU 校準。
- **輸出保護**：預設不覆寫既有檔案，輸出名稱帶有穩定來源後綴，避免不同來源的同名檔案互相覆蓋。

## 使用方式

以下步驟適用於已包含完整 runtime 的 App；從原始碼建立 App 請見下方「開發與建置」。

1. 開啟 **ASR Desktop.app**，到「模型」頁選擇模型，按「下載／修復」，等到顯示「已就緒」。
2. 到「匯入」頁加入音訊、影片或資料夾，選擇輸出資料夾、模型、裝置及文字格式。
3. 按「預覽批次」檢查檔案，再提交有效項目。
4. 按「恢復佇列」開始轉錄。服務每次啟動後，佇列預設為暫停。
5. 到「任務」頁查看進度、錯誤及輸出位置，也可取消或重試個別檔案或整批任務。

「暫停佇列」只停止下一檔，當前檔案會繼續；「停止背景服務」會先暫停領取，再等待當前工作完成。服務意外中斷後，需明確重試中斷的任務。

### 輸入與輸出

輸入為本機音訊或含音軌的影片。內建媒體工具包含 AAC、MP3、FLAC、ALAC、Opus、Vorbis 與常見 PCM 等音訊解碼器，實際可處理範圍取決於容器與音軌編碼。資料夾掃描不追蹤符號連結。

| 格式 | 內容 |
| --- | --- |
| TXT | 機器逐字稿，預設轉為台灣繁體，標示未經人工校訂 |
| SRT | 含時間碼的字幕，可設定每行長度與最長顯示時間 |
| JSON | 原始辨識文字及時間戳資料，不套用繁簡轉換 |

預設只輸出 TXT 與 SRT；JSON 需另外勾選或透過 `--formats` 指定。即使允許覆寫，也不能覆蓋來源媒體。

### 模型與裝置

| 模型 | CLI 識別名稱 | 約略下載量 |
| --- | --- | ---: |
| Fun-ASR-Nano（預設） | `fun-asr-nano` | 2.15 GB |
| Paraformer | `paraformer` | 1.30 GB |

下載量包含各模型需要的輔助資產；準備過程另需工作空間，以 App 顯示的需求為準。模型權重不放入 App 安裝檔，首次準備模型需要網路；推論不會自動下載缺少的模型。詳細流程見 [MODELS.md](desktop/MODELS.md)。

`auto` 目前因尚無合格品質基線而使用 CPU。可明確選擇 GPU／MPS，但一次成功轉錄或校準不會讓自動模式改用 GPU，也不代表 GPU 在所有錄音上都較快。判定條件見 [DEVICE-POLICY.md](desktop/DEVICE-POLICY.md)。

### CLI 範例

CLI 隨 App 提供。以下以 `/Applications` 為安裝位置；使用開發副本時，請改成簽署腳本輸出的 App 路徑。

```sh
ASR="/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop"

"$ASR" --help
"$ASR" diagnose --json
"$ASR" models download paraformer --json
"$ASR" models list --json
```

模型下載為非同步作業。確認 `models list` 中該模型的 `ready` 為 `true` 後，再提交轉錄：

```sh
"$ASR" submit "$HOME/Movies/meeting.mp4" \
  --output-dir "$HOME/Documents/Transcripts" \
  --model paraformer \
  --device auto \
  --formats txt,srt,json \
  --script traditional \
  --json

"$ASR" queue resume --json
"$ASR" jobs list --json
```

使用回應中的實際批次或任務 ID，替換下列 `batch-EXAMPLE`、`job-EXAMPLE`：

```sh
"$ASR" jobs watch batch-EXAMPLE
"$ASR" jobs show job-EXAMPLE --json
"$ASR" jobs cancel job-EXAMPLE --json
"$ASR" jobs retry job-EXAMPLE --json
```

`submit` 成功只表示接受提交；加上 `--wait` 才會等待整批結果。若佇列暫停、模型缺失或任務中斷，等待會回傳代碼 `3` 與 ID。Ctrl-C 只停止 CLI 觀察，取消背景工作需使用 `jobs cancel`。

可在設定頁按「安裝 CLI 連結」，或執行 `"$ASR" cli install`，建立 `~/.local/bin/asr-desktop`。程式不會覆寫同名命令，也不會自動修改 shell 的 PATH。更多命令與修復方式見 [USAGE.md](desktop/USAGE.md)。

## 資料儲存

| 資料 | 預設位置 |
| --- | --- |
| 任務資料庫、設定與轉錄紀錄 | `~/Library/Application Support/ASR Desktop` |
| 模型資產 | `~/Library/Application Support/ASR Desktop/models` |
| 可重建的音訊快取 | `~/Library/Caches/ASR Desktop` |
| TXT／SRT／JSON 成品 | 提交任務時指定的輸出資料夾 |
| 開發版背景服務日誌 | `/private/tmp/asr-desktop-<uid>/development-helper.log` |

GUI 與 CLI 透過同一使用者的私有 Unix socket 控制背景服務，由服務統一管理 SQLite 與單工推論佇列。模型下載與轉錄分開進行；缺少模型的任務會等待模型，不占用推論槽。

## 開發與建置

桌面版的 Swift 程式、文件與建置腳本位於 `desktop/`，Python 核心位於儲存庫根目錄的 `src/`。建置需取得完整儲存庫，並在根目錄執行以下命令。建置機需要：

- Apple Silicon Mac。
- Xcode（含 Swift 6 與 macOS SDK）。
- Python 3 與 `uv`；推論封裝環境固定使用 Python **3.11.15**。
- 首次取得依賴、FFmpeg 原始碼及模型時所需的網路與磁碟空間。

以下命令均在專案根目錄執行，產物放在 `build/desktop/`。若要重建正在使用的 App，請先停止其背景服務。

### 1. 建置原生 App

```sh
python3 desktop/scripts/build_app.py
```

產物為 `build/desktop/ASR Desktop.app`，包含 SwiftUI App、`asr-desktop` CLI 與 helper。三個執行檔均以 arm64／macOS 14 為建置目標，腳本會逐一檢查架構。**單獨完成此步尚不包含推論 runtime，需繼續以下步驟才能轉錄。**

### 2. 封裝推論環境與媒體工具

建立專用封裝環境，依固定版本安裝依賴：

```sh
uv venv --python 3.11.15 build/desktop/packaging-env
UV_CACHE_DIR="$PWD/build/desktop/uv-cache" uv pip install \
  --python build/desktop/packaging-env/bin/python \
  -r desktop/requirements/runtime.lock -r desktop/requirements/build.lock

python3 desktop/scripts/build_media.py
build/desktop/packaging-env/bin/python desktop/scripts/build_runtime.py
python3 desktop/scripts/verify_runtime.py
```

`build_media.py` 下載並驗證固定的 FFmpeg 原始碼，建置僅處理本機檔案的 FFmpeg／FFprobe，不連結 Homebrew 函式庫。`build_runtime.py` 使用 PyInstaller 收集推論環境並放入 App。

`verify_runtime.py` 從 App 路徑驗證套件匯入、OpenCC 轉換及媒體正規化，刻意排除開發機 Python 與 Homebrew PATH。報告位於 `build/desktop/runtime-verification.json`。缺少內建元件時，CLI 診斷會回傳代碼 `3`。

### 3. 建立開發簽署副本

```sh
build/desktop/packaging-env/bin/python desktop/scripts/collect_notices.py
python3 desktop/scripts/sign_development.py
```

簽署腳本會在 `/private/tmp` 建立獨立 App 副本，以避免雲端同步目錄的 Finder metadata 干擾簽章，並執行本機 ad-hoc 簽署與嚴格驗證。副本路徑會輸出至終端機，另存於 `build/desktop/development-signing.json`。

使用實際副本路徑啟動 App 或檢查服務：

```sh
open "/private/tmp/<副本目錄>/ASR Desktop.app"

"/private/tmp/<副本目錄>/ASR Desktop.app/Contents/MacOS/asr-desktop" diagnose --json
"/private/tmp/<副本目錄>/ASR Desktop.app/Contents/MacOS/asr-desktop" service start
"/private/tmp/<副本目錄>/ASR Desktop.app/Contents/MacOS/asr-desktop" service status
"/private/tmp/<副本目錄>/ASR Desktop.app/Contents/MacOS/asr-desktop" service stop
```

開發版會標示「開發模式」，由 GUI 或 CLI 直接啟動同一使用者的 helper。`build_app.py --distribution` 改用 SMAppService，仍需另行完成正式簽署、公證與生命週期驗收；該參數本身不會完成發行。

### 4. 封裝開發版 DMG（選用）

完成 runtime、第三方授權文字收集與簽署後，使用同一份開發副本：

```sh
python3 desktop/scripts/build_dmg.py --app "/private/tmp/<副本目錄>/ASR Desktop.app"
python3 desktop/scripts/verify_dmg.py
```

產物為 `build/desktop/ASR-Desktop-development-arm64.dmg`，內含 App、固定依賴與第三方授權文字，不含模型權重。開發簽署與 DMG 驗證不等於 Developer ID 簽署、公證或正式安裝驗收。使用 `sign_development.py --validation-environment` 建立的隔離測試副本不可當作一般開發版封裝。

## 測試與驗收

在上述封裝環境準備完成後，可執行 Python 與 Swift 測試：

```sh
PYTHONPATH=src build/desktop/packaging-env/bin/python \
  -m unittest discover -s tests/desktop -v
python3 desktop/scripts/build_app.py --test
```

完整 App 的模型與整合驗證另使用獨立建置資料及公開媒體範例：

```sh
python3 desktop/scripts/prepare_validation_models.py
python3 desktop/scripts/smoke_models.py
python3 desktop/scripts/verify_development_service.py --app "/private/tmp/<副本目錄>/ASR Desktop.app"
build/desktop/packaging-env/bin/python desktop/scripts/verify_batch.py
python3 desktop/scripts/verify_controls.py
```

`prepare_validation_models.py` 在 `build/desktop/validation-models` 準備模型，缺少的資產會從 catalog 固定版本下載並核對雜湊。現有開發者 hub 快取僅供讀取，不作為桌面版的模型儲存空間。

模型 catalog 位於 `src/asr_desktop/data/models.json`；維護者需要更新固定版本與資產雜湊時，可執行 `python3 desktop/scripts/update_model_catalog.py`。一般使用者下載模型不需更新 catalog。

## 專案結構

以下列出桌面版相關目錄；儲存庫亦保留既有 CLI 與 Drive 服務的程式及部署文件。

```text
ASR-Desktop/
├── desktop/
│   ├── Sources/
│   │   ├── ASRDesktopApp/       # SwiftUI 桌面介面
│   │   ├── ASRDesktopCLI/       # 原生 CLI
│   │   ├── ASRDesktopCore/      # 路徑、通訊、服務與診斷
│   │   └── ASRDesktopHelper/    # 背景服務啟動入口
│   ├── Tests/                  # Swift 原生測試
│   ├── scripts/                # 建置、簽署、封裝與驗證
│   ├── requirements/           # 桌面版固定依賴與媒體建置設定
│   ├── packaging/              # PyInstaller hooks
│   └── Package.swift           # Swift 套件定義
├── src/
│   ├── asr_desktop/             # 任務、模型、排程、裝置政策與輸出
│   └── asr_srt/                 # 本機轉錄與字幕核心
├── tests/desktop/              # Python 桌面版測試
└── pyproject.toml              # Python 套件定義
```

## 延伸文件

| 文件 | 內容 |
| --- | --- |
| [USAGE.md](desktop/USAGE.md) | GUI／CLI 操作、任務控制、常見問題與修復 |
| [MODELS.md](desktop/MODELS.md) | 模型準備、續傳、驗證、移除及離線使用 |
| [DEVICE-POLICY.md](desktop/DEVICE-POLICY.md) | CPU／GPU 自動選擇與效能證據要求 |
| [PROTOCOL.md](desktop/PROTOCOL.md) | 本機通訊協定、操作、事件與錯誤碼 |
| [VALIDATION.md](desktop/VALIDATION.md) | 歷史測試證據、實測環境與尚未完成的驗收 |

## Release Notes

以下保留既有版本紀錄；`v0.1.0` 涵蓋 CLI／Drive 服務，不代表桌面版已正式發行。

### 未發行 — ASR Desktop 開發版

- 新增 Apple Silicon 桌面視窗與 CLI，共用持久化批次、取消、重試、模型管理與設定。
- 安裝包內含辨識 runtime 與媒體工具；模型安裝後下載，使用完整性校驗與安全續傳。
- 批次輸出繁體 TXT、SRT 及可選原始 JSON，保護來源與既有檔案，匯出失敗可重用已完成辨識。
- `auto` 改為證據不足時使用 CPU；保留明確 GPU／CPU 與使用者啟動的校準。

驗證限制：已完成兩模型真實短檔批次與 CLI 控制測試；完整 GUI 操作、品質基線、長內容、乾淨 Mac／最低系統與正式簽署仍待驗收。此條目不代表已發布版本。

### v0.1.0 — 2026-09-22

- 可從網頁建立 Google Drive 音訊／影片轉錄批次，依序處理並查看任務進度。
- 支援 Google OAuth 登入，將逐字稿與 SRT 字幕交付到指定 Drive 資料夾。
- 提供任務暫停、失敗重試與重複掃描去重，保留已完成結果以便續傳。
- 提供 Mac mini 部署指南，以及可直接拉取的容器鏡像部署方式。
- 保留本機音訊／影片轉繁體中文字幕的 CLI 功能，並改善長音訊剩餘時間估算。

驗證限制：已完成短音訊的真實 Drive 下載、辨識與回傳；M4／16GB 長音訊仍需在目標機驗收。
