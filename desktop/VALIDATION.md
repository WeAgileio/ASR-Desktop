# Desktop validation evidence

## Scope — 2026-10-19

本紀錄涵蓋 OpenSpec 任務 1.1–1.6 的原生建置、獨立 runtime、固定模型資產與真實短片 smoke，以及背景控制程序的測試。桌面批次管理仍在實作；本紀錄不是完成產品、長錄音效能或正式分發驗收聲明。

實測硬體為 **Apple M1 Max、32 GiB、MacBookPro18,2**，系統 **macOS 26.6.2 arm64**。Swift 6.4；App 與媒體工具的 deployment target 為 macOS 14，但 macOS 14 目標機尚未驗收。

## Native build and runtime

- `python3 desktop/scripts/build_app.py` 產出三個原生 target，並逐一通過 `lipo -verify_arch arm64`。
- `python3 desktop/scripts/build_app.py --test` 通過 3 項原生測試，覆蓋空白路徑、App 定位及缺少內建元件時不退用系統依賴。
- Python 3.11.15 的獨立封裝環境由 77 個固定版本推論套件及獨立 build lock 建立，不修改既有 `.venv` 或 `.venv-worker`。
- `verify_runtime.py` 成功從 App 內啟動凍結 helper。測試移除 Homebrew／開發 PATH 並設定無效的外部 Python 環境，FunASR AutoModel、Qwen3、OpenCC、FFmpeg 與 FFprobe 均可執行；實際 WAV 正規化結果為 16 kHz 單聲道。
- FFmpeg／FFprobe 8.0.1 由 SHA-256 固定的上游原始碼建置；`otool -L` 僅列出 macOS 系統函式庫，`LC_BUILD_VERSION` 的 minos 為 14.0。未複製 Homebrew 執行檔來充當獨立元件。
- 第一輪凍結驗證發現 Transformers metadata 遺漏，已在建置收集中補齊完整 runtime 套件 metadata，重新凍結後診斷通過。

詳細報告為忽略追蹤的 `build/desktop/runtime-verification.json` 與 `runtime-verification.stderr.log`。

## Fixed model assets

| Component | Immutable revision | Verified assets |
| --- | --- | ---: |
| Fun-ASR-Nano | `05201c46f1c38592b1567f857c0d56eab3d0d8ef` | 12 |
| Paraformer | `0141367fdc9b6ba58b0442ef34bceb56a6c1789c` | 7 |
| FSMN VAD | `f9a8b8274674755d925277e27063869038d41515` | 5 |
| CT punctuation | `d488ddd5985989501d57bce7f7a4d4dcfca779d0` | 5 |

Catalog 包含權重、設定、Qwen tokenizer、VAD、標點及模型說明來源。所有 29 個資產已按大小與 SHA-256 驗證。既有相符快取只建立獨立的驗收複本；缺少的標點模型從固定版本下載，沒有修改使用者 hub 快取。snapshot manifest 位於 `build/desktop/validation-models/manifest.json`，模型不放在 App 安裝檔中。

## Packaged real-model smoke

使用 Fun-ASR-Nano 模型隨附的公開 `zh.mp3`、`en.mp3`，先以內建 FFmpeg 解碼，再把中英文例句串成 mixed 測例。每個案例由獨立的 App helper 執行，固定所有模型本機路徑，封鎖 helper 的 Python socket 外連。八個案例均實際辨識成功，文字非空、時間戳非空、順序及媒體邊界檢查通過。

| Model | Device | Case | Load + inference seconds | Timestamp units | Peak RSS MiB |
| --- | --- | --- | ---: | ---: | ---: |
| Nano | CPU | Mandarin | 20.785 | 14 | 6729.2 |
| Nano | CPU | Mixed | 21.411 | 33 | 5733.2 |
| Nano | MPS | Mandarin | 20.339 | 14 | 5984.8 |
| Nano | MPS | Mixed | 20.315 | 33 | 7047.9 |
| Paraformer | CPU | Mandarin | 4.601 | 13 | 3375.5 |
| Paraformer | CPU | Mixed | 4.784 | 28 | 3375.7 |
| Paraformer | MPS | Mandarin | 8.019 | 13 | 3379.6 |
| Paraformer | MPS | Mixed | 4.864 | 28 | 3380.0 |

結果、原始 transcript、stderr 與載入／推論 spans 保存在 `build/desktop/smoke-models/`。此處沒有可泛化的字錯率結論；短片樣本不符合未來自動裝置比較所需的長度、樣本數與完整資源觀測，不能用來自動提升 GPU 預設。Python 層封鎖外連也不取代後續作業系統層的完全離線驗收。

## Background bootstrap

`PYTHONPATH=src build/desktop/packaging-env/bin/python -m unittest tests.desktop.test_coordinator_bootstrap -v` 的 5 項測試通過：實際使用者 peer 身分及 0700／0600 權限、單例鎖、版本不相容不允許停止、正常停止回收，以及拒絕不安全／符號連結的控制目錄。

最早的 bootstrap 只提供狀態／停止並標示 `execution_ready=false`。後續加入模型、SQLite、worker 與排程後改為 true；模型準備狀態及各任務結果仍分開判定。

### Formal SMAppService acceptance remains pending — task 8.2

- 修正 LaunchAgent 的非完整路徑 `argv[0]` 問題：原生程式改以 `_NSGetExecutablePath` 定位 App，另以刻意改名的 argv[0] 呼叫 CLI 診斷，結果成功。
- iCloud 目錄會重新附加 App 根目錄 FinderInfo，導致簽章驗證失敗。`sign_development.py` 改在 `/private/tmp` 建立獨立驗收副本，只移除副本的 FinderInfo／ResourceFork，保留其他安全屬性；副本通過 `codesign --verify --deep --strict`。
- 直接啟動已簽署副本中的 helper，實際控制 socket 可以查詢並正常停止；這不代表 launchd 生命週期已通過。
- SMAppService 註冊可以回報 enabled，但 launchd 拒絕啟動。相符時間與副本路徑的 AMFI 日誌包含 `has no CMS blob?`、`Unrecoverable CT signature issue`、`Launch Constraint Violation`，launchd 退出原因為 `OS_REASON_CODESIGNING`。
- `security find-identity -v -p codesigning` 回報 0 個可用身分。本次只使用 ad-hoc 簽署，沒有宣稱具備 Apple 發行簽章或公證。
- 使用者已明確選擇先以開發 profile 直接啟動 helper；正式 profile 不允許在受管理服務失敗時靜默降級。簽署與 managed lifecycle 保留為任務 8.2 的發行門檻。
- 此次測試 LaunchAgent 已透過 App 的 unregister 操作清除；`launchctl print` 確認測試標籤不存在，紀錄位於 `build/desktop/service-cleanup.json`。

[Apple DTS 的相關說明](https://developer.apple.com/forums/thread/799910)建議 App 與內嵌 helper 使用相同的 Apple 簽署身分，並指出 ad-hoc 簽署可能造成服務問題；此處仍以本機實際 AMFI／launchd 日誌為阻礙證據。

## Remaining acceptance

尚待完成：完整 GUI 操作、審閱品質基線、乾淨 Mac／macOS 14、長錄音資源驗收、正式簽署與公證。不得以本次開發機 smoke 代替上述項目。

## Development lifecycle and second clean build — 2026-10-20

- 開發 profile 的 Info.plist 明確設定 `ASRDesktopDevelopmentMode=true`；未標示或正式 profile 均拒絕直接 helper 啟動。原生測試涵蓋這個分界。
- `verify_development_service.py` 使用打包副本、獨立 0700 控制目錄、移除開發 PATH 及無效外部 Python 路徑，證實 CLI 退出後存活、重複 start 仍同一 PID、socket 0600、stop 清理，以及停止後 status 回傳 3。
- 實際 SwiftUI 視窗顯示開發模式與運作狀態。透過視窗關閉按鈕關窗，再退出 App；`pgrep` 確認 App 程序已退出，CLI 回應的 helper PID 前後均為 46349。測試服務已正常停止。
- 在新的 `packaging-verify-env` 安裝全部鎖定依賴（僅使用已下載的 uv 快取），重新凍結並組裝 App，`verify_runtime.py` 的完整 import／實際媒體正規化再次通過。這是同一台 Mac 上的第二個乾淨 Python 封裝環境，並非第二台 Mac 或 macOS 14 驗收。
- 證據保存在 `build/desktop/development-service-verification.json`、`second-runtime-build.log`、`runtime-verification.json`。

## Packaged functional evidence — 2026-10-20

- **121 source regression tests and 5 native tests pass.** Native coverage includes build-profile isolation, paths, command-link conflict protection, and refusing readiness for a damaged or failing runtime.
- Model-store coverage includes shared preparation, capacity/offline errors, validated Range/ETag resume, HTTP 416 restart, checksum failures, interrupted publication, retained old definitions and active-job references. A real local HTTP transfer stops after 7,000 bytes and resumes with the correct Range/If-Range before passing the original checksum.
- The complete local adapter passes all **8 packaged model/device/language smoke cases** again. Nonempty text, ordered/bounded timestamps and Python outbound-network blocking remain enabled. This does not establish a reviewed quality baseline.
- `verify_batch.py` submits two public files each for Nano and Paraformer through the packaged Swift CLI/coordinator/worker. All four complete with nonempty Traditional Chinese TXT, valid SRT and original JSON. Auto chooses CPU with insufficient-evidence reasoning. Models and job data use independent build-only fixtures.
- `verify_controls.py` exercises real cancellation/retry, identical request replay, Ctrl-C returning 130 while work continues, refusal to remove an active model, sequential CPU/MPS calibration, and partial output failure while the other file succeeds. Exit codes **0/1/2/3/130** are covered; preexisting output content remains unchanged.
- Native `diagnose --json` starts the frozen runtime rather than trusting file presence. It reports ready/frozen with developer PATH removed and invalid external Python paths.
- Workers save separate loading/inference spans, per-process RSS and pressure/swap observations. Ordinary observations have no reviewed quality certification and cannot automatically promote GPU.

Reports: `build/desktop/regression.log`, `batch-integration/report.json`, `control-integration/report.json`, `native-diagnose.json`, and `runtime-build-inputs.json`.

A further MP4 fixture with both a real video stream and AAC audio completes through the packaged Paraformer CLI and produces TXT/SRT (`build/desktop/video-integration.json`). Homebrew FFmpeg only generated the black-video/public-audio fixture; the actual inference ran with restricted PATH and bundled media tools. This does not extend the result to untested video codecs or long recordings.

An additional seven-case socket suite passes after the full regression: the real private transport rejects a controlled foreign-peer identity without stopping the service. Actual same-user identity is checked through the OS API in the positive case. This boundary test does not replace fresh-account acceptance (task 6.1).

## GUI acceptance still incomplete

The signed development copy with local private fixture data visibly loads the same CLI history: **12 jobs, 11 completed, 1 failed**. Its window shows development mode and the persisted paused queue. The shared socket reports PID 63696; CLI settings updates are accepted by that same service. Visual confirmation of those subsequent settings changes is still pending.

An earlier GUI test using an iCloud data root stalled in `os_open` without publishing a socket. CLI tests at that location worked. The exact cause remains unconfirmed; it is not established as a specific TCC or File Provider failure. Equivalent local private data loads successfully. Product data defaults to local Application Support; complete authorization of iCloud source media still requires acceptance testing.

Then UI automation reported `Sky Computer Use native pipe closed before response`. Reset/rebind did not recover it. Full model-screen, file-dialog, details, cross-interface control and error-recovery interaction tests remain open, so tasks 7.1–7.5 remain unchecked. The private test service was stopped and its socket removed. No operating-system protection was disabled.

## Development image

`build/desktop/ASR-Desktop-development-arm64.dmg` is **378.3 MiB** and contains the CLI, helper, fixed catalog, standalone media tools and distribution notices, without model weights. Runtime input fingerprints match before/after freezing. The App passes ad-hoc deep/strict signing verification and the image checksum passes.

The image was mounted read-only. All **281 Mach-O files** pass arm64 verification, with no non-system absolute external dependencies. Deep/strict verification and full frozen-runtime CLI diagnosis pass from the relocated mounted App with developer Python/PATH removed. The image was detached. Reports are `dmg-verification.json` and `dmg-mount-verification.json` under `build/desktop`.

This is not Developer ID signing, notarization, Gatekeeper, clean-Mac or minimum-OS acceptance. No Git commands or publishing were performed.
# 跨版本 App 演練

`verify_app_upgrade.py` 接受兩個不同版本、不同 runtime 的完整開發版 App，將它們依序複製到同一暫存安裝位置，演練舊版 → 新版 → 舊版。所有服務、資料庫、測試音檔與模型副本使用獨立暫存目錄；既有模型目錄只作為複製來源。服務每次切換前必須停止，佇列全程暫停，不執行模型品質評測。

```sh
python3 desktop/scripts/verify_app_upgrade.py \
  --old-app '/path/to/old/ASR Desktop.app' \
  --new-app '/path/to/new/ASR Desktop.app' \
  --models "$HOME/Library/Application Support/ASR Desktop/models" \
  --report build/desktop/app-upgrade-verification.json
```

核對項目包含任務與設定保留、模型資產 SHA-256 不變、重連同一 helper、SQLite integrity_check、舊 runtime 拒絕 synthetic future schema 且資料庫未變，以及完整備份還原後重新連線。若兩版 schema 相同，這只證明相同 schema 的跨版本相容；schema 升級另由 `tests.desktop.test_workspace.SchemaTests` 的版本 0 fixture 驗證。此演練不包含 GUI、正式簽署或乾淨 macOS 14 驗收。

