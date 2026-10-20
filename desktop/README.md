# ASR Desktop development

目標平台為 Apple Silicon／macOS 14+。已提供視窗、CLI、共享模型 store 與單工協調程序。日常操作見 [USAGE.md](USAGE.md)，模型準備見 [MODELS.md](MODELS.md)。最低系統與正式發行仍待驗收。

## Native build

建置機需要 Xcode（含 Swift 6）與 Python 3；這些是開發依賴，最終使用者不需另行安裝。

從專案根目錄執行：

```sh
python3 desktop/scripts/build_app.py
```

產物位於 `build/desktop/ASR Desktop.app`。建置腳本明確使用 arm64 與 macOS 14 deployment target，並逐一檢查三個執行檔架構。完整 runtime 依下節另行收集；目前為開發 App，完整 GUI、品質／長語料與正式安裝驗收尚未完成。

```sh
"build/desktop/ASR Desktop.app/Contents/MacOS/asr-desktop" --help
"build/desktop/ASR Desktop.app/Contents/MacOS/asr-desktop" diagnose --json
python3 desktop/scripts/build_app.py --test
```

診斷使用 App 內部的絕對路徑，不借用開發機的 Python 或 FFmpeg；缺少元件會回傳 3。模型將在安裝後由 App 或 CLI 下載，不放進安裝檔。

## Standalone inference runtime

建立獨立的 Python 3.11.15 封裝環境，再安裝完整固定版本。不要在既有 worker 環境中安裝封裝工具：

```sh
uv venv --python 3.11.15 build/desktop/packaging-env
UV_CACHE_DIR="$PWD/build/desktop/uv-cache" uv pip install \
  --python build/desktop/packaging-env/bin/python \
  -r desktop/requirements/runtime.lock -r desktop/requirements/build.lock
python3 desktop/scripts/build_media.py
build/desktop/packaging-env/bin/python desktop/scripts/build_runtime.py
python3 desktop/scripts/verify_runtime.py
```

`build_media.py` 下載並檢查固定 FFmpeg 原始碼，建置只處理本機檔案的 arm64 FFmpeg／FFprobe，不連結 Homebrew 函式庫。支援的音訊解碼包括 AAC、MP3、FLAC、ALAC、Opus、Vorbis 與常見 PCM；不包含下載網路影音功能。來源、設定及授權文字一併放入產物。

`verify_runtime.py` 從 App 路徑執行 helper，將 PATH 限制為系統目錄並刻意設定無效外部 Python 路徑，確認 FunASR／Qwen3 等套件可匯入、OpenCC 可轉換，以及內建媒體工具可輸出 16 kHz 單聲道 WAV。報告位於 `build/desktop/runtime-verification.json`；這項檢查不代表長音訊或最低 macOS 版本驗收已通過。

## Model catalog and packaged smoke

安裝後模型管理所用的 catalog 位於 `src/asr_desktop/data/models.json`。更新 catalog 是維護者動作，需要網路，只讀公開模型 metadata，將每個元件固定到 commit 與 SHA-256：

```sh
python3 desktop/scripts/update_model_catalog.py
```

下列命令只供建置驗收。它們在 `build/desktop/validation-models` 準備獨立模型複本，現有 hub 快取只供讀取；缺少資產從 catalog 的固定版本下載，逐一核對大小與雜湊。

```sh
python3 desktop/scripts/prepare_validation_models.py
python3 desktop/scripts/smoke_models.py
```

Smoke 使用模型隨附的公開中文及英文例句，將例句組成中英混合測例，逐一執行兩個模型／兩種裝置。helper 內封鎖 Python 網路連線並記錄真實文字、時間戳、載入／推論 spans 和 RSS；結果位於 `build/desktop/smoke-models/report.json`。短片 smoke 不當成自動裝置政策的長錄音品質或效能證據。

## Development signing and service status

```sh
python3 desktop/scripts/sign_development.py
```

此命令在 `/private/tmp` 建立獨立的 App 驗收副本，避免 iCloud 目錄重新附加 Finder metadata。它只清除副本中簽章不相容的 FinderInfo／ResourceFork，做本機 ad-hoc 簽署及嚴格驗證，不移除 quarantine，也不等於正式簽署或公證。副本位置保存於 `build/desktop/development-signing.json`。

開發建置會明確標示「開發模式」，由 GUI 或 CLI 以同一使用者直接啟動 helper；關閉視窗與 CLI 不會停止服務。stdio 寫至私有控制目錄的 `development-helper.log`，不使用 root、不改變系統防護。使用簽署腳本輸出的副本路徑執行：

```sh
"/private/tmp/<副本目錄>/ASR Desktop.app/Contents/MacOS/asr-desktop" service start
"/private/tmp/<副本目錄>/ASR Desktop.app/Contents/MacOS/asr-desktop" service status
"/private/tmp/<副本目錄>/ASR Desktop.app/Contents/MacOS/asr-desktop" service stop
python3 desktop/scripts/verify_development_service.py --app "/private/tmp/<副本目錄>/ASR Desktop.app"
```

正式 profile 使用 `build_app.py --distribution`，保留 SMAppService，失敗時不降級。此機器沒有 Apple 簽署身分，ad-hoc helper 被 AMFI 啟動約束拒絕；正式簽署與受管理服務驗收仍未完成，詳見 [VALIDATION.md](VALIDATION.md)。目前 service health 的 `execution_ready=true` 表示可接受並處理就緒任務；每筆任務仍各自檢查模型及來源，不能將此欄位當作正式發行驗收。

重現第二個乾淨封裝環境可將上述 `packaging-env` 全部替換為 `packaging-verify-env`，重新建立 venv、安裝相同 lock、執行 `build_runtime.py` 與 `verify_runtime.py`。同機隔離環境驗證已通過；乾淨 Mac 與最低系統驗收另外執行。

## Development image and integration checks

```sh
build/desktop/packaging-verify-env/bin/python desktop/scripts/collect_notices.py
python3 desktop/scripts/sign_development.py
# Use the App path printed by the signing script:
python3 desktop/scripts/build_dmg.py --app "/private/tmp/<stage>/ASR Desktop.app"
python3 desktop/scripts/verify_dmg.py
```

The image is `build/desktop/ASR-Desktop-development-arm64.dmg`. It contains notices and the fixed runtime, without model weights or notarization. Stop the helper before rebuilding its App directory. The signing script's `--validation-environment` is only for isolated GUI test copies; those copies cannot be packaged as the ordinary development image.

After preparing public validation examples and snapshots:

```sh
build/desktop/packaging-env/bin/python desktop/scripts/verify_batch.py
python3 desktop/scripts/verify_controls.py
```

These use separate build data and public media. They verify real packaged batches, exports, cancellation, retry, request replay, Ctrl-C, calibration, partial failure and exit codes. `build_runtime.py --clean` forces new analysis and checks that runtime sources remain unchanged during freezing; fingerprints are saved in `runtime-build-inputs.json`.
