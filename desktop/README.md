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

## 品牌素材

原始 Logo 位於 `Sources/ASRDesktopApp/Resources/karakuri-mark.svg`。主視窗使用同目錄的
`karakuri-mark-light.pdf` 與 `karakuri-mark-dark.pdf`，保留向量輪廓及綠色圓點，依系統外觀切換主體顏色。
更新 SVG 後，從專案根目錄執行以下命令重新產生兩份向量素材，再執行一般 App 建置：

```sh
swift -module-cache-path build/desktop/cache/swift desktop/scripts/build_brand_assets.swift
python3 desktop/scripts/build_app.py
```

同一個轉換器也會產生 `Resources/ASRDesktop.icns`，包含 16–1024 像素圖示，使用淺色圓角底與原始 Logo。
建置時將此檔案放入 `Contents/Resources`，並透過 `CFBundleIconFile` 提供 Dock／Finder 圖示。

轉換器只接受此 Logo 使用的 SVG 路徑指令與圓形；若修改為其他 SVG 元素或指令，需先擴充轉換器。
`Package.swift` 將素材納入 SwiftPM 資源 bundle；`build_app.py` 將該 bundle 複製至 App 的 `Contents/Resources`，
以符合 macOS 簽章要求。App 優先從此處載入，開發執行則回退至 `Bundle.module`。
封裝時須保留此 bundle，不可僅複製執行檔。
Logo 與底部 `karakuri.tech` 來源文字均可離線顯示；只有啟用來源連結時才透過系統預設瀏覽器開啟網站。

## Standalone inference runtime

runtime 現在另包含 faster-whisper／CTranslate2／PyAV／ONNX Runtime 及 Transformers Whisper，
用於 Taiwan Tongues 與 Breeze ASR 25 的本機 CPU 推論。需依更新後的 runtime.lock 安裝並重新凍結，
只重建 Swift 介面不會更新 Python 推論引擎。模型與電腦需求說明見 `MODELS.md`。

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

### Beta release packaging

在 `pyproject.toml` 設定 beta 版本（例如 `0.2.0b1`），並在根目錄 README 的 Release Notes 加入對應的 `v0.2.0-beta.1` 條目。準備好下述 locked packaging environment 與媒體工具後執行：

```bash
python3 desktop/scripts/package_release.py
# 已有來源指紋一致的 frozen runtime 時，可使用：
python3 desktop/scripts/package_release.py --reuse-runtime
```

腳本會編譯 App、收集授權、建立獨立簽署副本、產生帶版本號的 DMG、掛載驗證及產生 `.sha256` 與 `release-notes.md`。產物位於 `build/desktop/`。這是 ad-hoc 簽署的 Apple Silicon 測試版，不含 Apple 公證；模型於安裝後下載。

發佈前依專案規則確認 Git 指令及變更範圍，再依序 pull、commit、建立 annotated tag、push，最後用 `gh release create` 搭配 `--verify-tag --prerelease --notes-file build/desktop/release-notes.md` 上傳 DMG 與校驗檔。打包腳本本身不執行 Git 或遠端發佈。

### GitHub Actions 建置與發版

`.github/workflows/desktop-release.yml` 使用 macOS 15 ARM64 runner，安裝固定 Python 3.11.15 與 locked dependencies，執行桌面單元測試、編譯內建 FFmpeg、打包與掛載驗證 DMG，再檢查 frozen runtime 與媒體轉換。

CI 透過 `DEVELOPER_DIR` 明確選用 Xcode 16.4，記錄 Xcode／Swift 版本並執行 Swift 原生測試。品牌圖片資源限定於 MainActor，符合此工具鏈對 AppKit 圖片共用狀態的並行安全檢查。

- 手動測試：在 GitHub → Actions → **Build desktop DMG** → **Run workflow** 選擇分支。成功後從該次執行的 Artifacts 下載 DMG、SHA-256 與 release notes；保留 14 天，不建立 Release。首次使用需先將 workflow 推送到預設分支。
- 發版：依專案確認流程完成 pull、commit，建立並推送 annotated tag（例如 `v0.2.0-beta.1`）。標籤必須符合 `pyproject.toml` 的 `0.2.0b1`，README 必須已有該版本說明。驗證通過後，Actions 自動以 `gh release create` 建立 GitHub prerelease 並附上 DMG 與校驗檔，不需在本機另外建立 Release。
- 建置工作僅有讀取權限；發佈工作才使用 GitHub 自動提供的 `GITHUB_TOKEN` 寫入 Release，無須額外的個人 token。相同 Release 已存在時會失敗，不覆寫既有附件。

此 workflow 僅支援 beta、Apple Silicon 與 ad-hoc 簽署；不含 Apple Developer ID 或公證，因此下載後仍可能遇到 macOS 的安全性阻擋。CI 不下載大型模型，也不替代真實模型轉錄及最低 macOS 版本驗收。現有 container workflow 仍會依自己的標籤規則執行。

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
