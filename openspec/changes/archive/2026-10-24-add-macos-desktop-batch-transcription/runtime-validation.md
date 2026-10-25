# Current follow-up — 2026-10-24

目前任務清單為 **45/45 完成、0 項待完成**。使用者已取消 8.2，該項不計入待辦或已完成數；下方先前紀錄保留為歷史證據。

## User final acceptance — 2026-10-24

使用者針對 8.3（乾淨 Apple Silicon／最低 macOS 14 環境）與 8.4（長錄音整合）明確確認「那兩個我也都驗收完了」，據此將兩項記錄為使用者驗收通過。未由代理重跑或提供額外實測數據；先前待驗收敘述保留為歷史紀錄。目前所有 45 項有效任務完成，8.2 仍為取消，尚未歸檔。

## User GUI acceptance — 2026-10-24

使用者明確確認「gui我自己都驗收完了」。7.1–7.5 依使用者驗收結果完成；代理未追加執行 GUI 驗收，以下工具逾時與未完成描述為當時歷史狀態。剩餘項目為 8.3、8.4。

## Repackaged App and GUI retry — 2026-10-24

- 建立鎖定 Python 3.11.15 封裝環境，重新編譯原生 targets 並凍結目前 Python 原始碼。新增 build_app.py 的 --scratch-path 選項，使用非同步目錄的 Swift 建置路徑；56 項相關 Python 測試與 7 項 Swift 測試通過。沿用安裝版固定 FFmpeg 8.0.1 媒體工具與來源告知，重新收集 Python 授權。
- 可使用的 ad-hoc 簽署 App：`/private/tmp/asr-desktop-dev-h21ac6wb/ASR Desktop.app`。版本仍為 0.2.0b2，本機未發行重建；未提交、推送或發布。簽章完整性、凍結 runtime 診斷與真實媒體正規化通過。透過新版 helper socket 建立兩個測試批次，確認批次篩選計數只包含一筆；證據位於 build/desktop/packaged-count-verification.json，來源指紋在 runtime-build-inputs.json 與 repackage-verification.json。
- GUI 驗收副本 `/private/tmp/asr-desktop-dev-0jkemn2w/ASR Desktop.app` 使用 `/private/tmp/asr-gui-repack-ipm6r928` 獨立資料／socket／快取與模型副本。成功觀察匯入頁、模型需求、大小與 Nano／Paraformer 已就緒，另兩模型尚未下載。
- 在隔離 Paraformer 副本移走 config.yaml 後，點「重新驗證」確認不再顯示就緒，畫面回報資產缺失／損壞及 preparation 修復提示。點「下載／修復」後 CUA 逾時、重連出現 noWindowsAvailable；依工具列出的 /tmp 路徑重試仍 timeoutReached。CLI 確認修復下載有進度，服務正常；未發現 ASRDesktopApp 崩潰紀錄，尚不能判定視窗問題原因。
- 7.1／7.5 增加以上部分證據，但修復完成的 GUI 畫面及其餘互動仍未驗收，任務計數不變。隔離資料不影響使用者原有任務與模型，未替換 /Applications 中的 App。
- 後續 CLI 確認 Paraformer 修復完成、ready=true。完整 App 壓縮檔為 build/desktop/ASR-Desktop-local-rebuild-20261024.zip，SHA-256：9620f4ce6a25a7a1e0f87c1a223ce1d3ce4bd1b1c4b804a3571a9345cd4c51a8。GUI 完成狀態仍未觀察。

## Tasks 7.5, 7.4, 7.2 and 7.3 non-GUI follow-up

- 依使用者指定順序完成非 GUI 檢查，詳見 [操作對照與驗收證據](../../../desktop/NON-GUI-ACCEPTANCE.md)。錯誤修復／服務 22 項、操作／批次／進度 34 項測試全部通過。
- 真實安裝版 App 副本完成缺失／損壞 runtime 診斷與還原；隔離 CLI／FFprobe 完成混合檔、去重、遞迴、缺模型、輸出計畫與整批取消演練。未進行模型品質驗證，未操作使用者任務或修改已安裝 App。
- 修正批次篩選後 counts 仍統計全域任務的錯誤，新增回歸測試；修正目前僅在原始碼。四項仍待 GUI 驗收，總進度維持 38/45。

## Task 8.5 cross-version acceptance — completed

- 使用安裝版 0.1.0 與 GitHub v0.2.0-beta.2 的完整 App，透過 `desktop/scripts/verify_app_upgrade.py` 在相同暫存安裝位置依序替換 0.1.0 → 0.2.0b2 → 0.1.0。安裝包 SHA-256 為 `3423607e8c9a9f1aa26f149b2c1118107e6d090c093143df239f78abc7c78b59`，與 GitHub 發布資產一致；兩版 CLI 與 runtime 雜湊不同，詳見 [完整報告](app-upgrade-verification.json)。
- macOS 26.6.2 arm64 實測通過：各階段 helper 啟動／重連、佇列暫停、一筆測試任務與設定保留、SQLite integrity_check，以及 38 個原有模型儲存檔案 SHA-256 不變。以獨立副本操作；沒有替換 `/Applications` 或修改使用者原有資料。
- 兩版資料庫都是 schema 1，未發生真實 schema 變更；版本 0 fixture 的升級與備份測試另已通過。真實舊版 runtime 對 synthetic schema 999 回傳啟動失敗，日誌確認 newer-schema 原因，資料庫雜湊不變。還原停止服務時取得的完整資料目錄備份後，舊 App 再次啟動並保留任務、設定與模型檔案。
- 隔離測試服務均已停止，暫存安裝／資料副本已清理，唯讀 DMG 已卸載。README 未發行條目與操作指南已同步已驗證範圍；8.5 勾選完成，OpenSpec strict validate 通過。本次未做 GUI、正式簽署、最低系統或模型品質驗收。

## Task 8.5 non-GUI verification

- 新增版本 0 測試資料升級後，將自動備份還原到獨立資料庫的測試：原有內容保留、還原資料庫維持舊版本且不含升級後設定；重開升級後資料庫仍保留設定且不重複升級。這是 schema fixture，並非已發行舊版 App 的完整資料庫。
- `PYTHONPATH=src build/desktop/test-env/bin/python -m unittest tests.desktop.test_workspace tests.desktop.test_models -q`：21 項全部通過，包含較新 schema 拒絕寫入且檔案不變、模型 catalog 更新後保留原 snapshot。初跑遇 Python 3.9 的 HTTPError 空回應替身關閉問題，將測試替身改為 BytesIO 後通過，未變更產品下載邏輯。
- `python3 desktop/scripts/verify_development_service.py --app '/Applications/ASR Desktop.app'`：隔離資料／socket 目錄驗證通過，包含重複啟動共用 PID、CLI 結束後服務存活、私有權限、停止清理及停止後退出碼 3；不影響原本服務。報告位於 `build/desktop/development-service-verification.json`。此驗證針對已安裝 App，不代表本次 Swift 修改已封裝進該 App。
- `desktop/USAGE.md` 補齊停止與備份、完整 App 更新、重連核對及資料庫回退步驟；README 新增未發行條目及驗證限制。OpenSpec strict validate 通過。
- 8.5 尚缺兩個具體 App 版本間的實際替換／回退演練，維持未完成；8.3 的乾淨 macOS 14 與 8.4 的代表性長錄音實機驗收亦不能用本輪測試代替。目前仍為 37/45。

## Earlier tasks 5.6 and 6.1 verification

- 使用者明確表示「模型驗證不需要驗證了」，因此移除 5.6 的品質／時間戳基線驗收工作，保留程式回歸及政策文件。未將未做的模型品質驗收記為通過，也未放寬 `auto` 的證據門檻。
- 建立 `build/desktop/test-env` 隔離環境，使用 Xcode Python 3.9.6，安裝 OpenCC、Rich、RQ、HTTPX、Pydantic 等測試依賴。初次執行暴露缺少 HTTPX／Pydantic，補齊後以下命令 **63 項測試全部通過**：

  `PYTHONPATH=src build/desktop/test-env/bin/python -m unittest tests.desktop.test_evidence tests.test_workflow_cli tests.test_longform tests.test_adapters_device tests.test_progress_performance tests.test_service_outputs tests.service.test_execution tests.service.test_drive -q`

- 以上為受控資料與替身的程式回歸，未對真實 Drive 寫入或進行真實模型品質評測。裝置政策說明已同步 `desktop/DEVICE-POLICY.md`；修訂後的 5.6 已完成。
- 修正 `ServiceClient.ensureReady`：現有連線、開發 helper 回應與正式服務啟動後輪詢，均須確認回應成功、狀態為 running 且 execution_ready 為 true；失敗、停止中或不完整回應不能被當作就緒。
- 新增兩項 Swift 測試，涵蓋停止中／未就緒、錯誤、不完整或損壞回應。原生 targets 建置成功，**7 項 Swift Testing 測試全部通過**。首輪受沙箱外編譯快取限制，改用本機快取後又遇 iCloud 建置目錄的 Finder 屬性導致 ad-hoc 簽章失敗；將建置輸出移至 `/private/tmp` 後通過，沒有變更系統保護。

  `CLANG_MODULE_CACHE_PATH=/private/tmp/asr-desktop-swift-cache SWIFTPM_MODULECACHE_OVERRIDE=/private/tmp/asr-desktop-swift-cache swift test --package-path desktop --scratch-path /private/tmp/asr-desktop-validation-20261024 --cache-path /private/tmp/asr-desktop-validation-cache/packages --config-path /private/tmp/asr-desktop-validation-cache/config --security-path /private/tmp/asr-desktop-validation-cache/security --disable-sandbox`

- 6.1 的新帳號首次啟動與背景權限驗收由使用者明確確認「這個我已經驗收通過了」，據此勾選完成；代理未重新執行該帳號驗收。本次原生建置未替換 `/Applications` 內安裝的 App。

## Task 7.1 UI connection blocker

- 使用者同意停止失聯程序後，重新確認 PID 23960 是安裝版 runtime，再送 SIGTERM；舊程序釋放資料鎖，CLI `service start --json` 成功啟動 PID 62740，回報 running／execution_ready=true。GUI 與 CLI 均確認佇列暫停，模型列表一致；未刪除資料或鎖檔。
- 從 GUI 啟動 Paraformer 下載，觀察到「下載中」及進度 0 → 3.24%，CLI 後續確認 downloaded_bytes=857764003、ready=false，沒有提早標成已就緒。下載仍在進行，尚未驗證完成與失敗重試，因此不勾選 7.1。
- 7.2 使用 `/private/tmp/asr-gui-acceptance` 的隔離 fixtures（一秒靜音 WAV、子目錄 WAV、無效文字檔及獨立輸出目錄），GUI 成功定位輸入資料夾，但按 Open 與後續讀取介面連續回報 `Computer Use server error -10005: timeoutReached`。尚未確認資料夾加入結果，未提交測試轉錄；CLI 查詢仍正常，這次阻礙為介面工具逾時。
- 後續 CLI 確認 Paraformer 完整下載 1,296,116,062 bytes，state=ready、ready=true；兩模型現皆就緒。CUA 重設後仍逾時，無法核對下載完成的 GUI 狀態與重試操作，7.1／7.2 保持未完成。

- 續作時 CUA 已恢復，可讀取模型與設定頁。模型頁顯示 Nano 下載量／占用 2.15 GB、已就緒；Paraformer 下載量 1.3 GB、所需空間 1.31 GB、尚未下載。這些是畫面觀察，尚未確認為目前服務狀態。
- CLI `models list --json` 在一般與提升權限環境均退出 3，回報服務未連線；GUI 設定頁亦出現相同訊息，按「啟動／重新連線」未恢復。日誌顯示 `A coordinator already owns this data directory`。`lsof` 顯示 PID 23960 持有使用者資料目錄的 coordinator.lock 及原 control.sock，但 `/private/tmp/asr-desktop-501/` 已無該 socket 路徑。判斷目前存在持鎖程序與不可連線端點；其工作是否仍在執行尚未確認。
- 未終止該程序、刪除鎖檔或變更使用者資料。7.1 仍未完成，需先恢復既有服務連線，或改用隔離驗收環境；先前的 CUA 連線故障已不再是目前阻礙。

- CUA 成功讀取 `/Applications/ASR Desktop.app` 的匯入視窗：開發模式、佇列運作中、四個頁籤、模型／裝置／文字選項與匯出格式可見；未選來源及輸出位置時，預覽與提交按鈕均停用。
- 點擊模型頁時回報 `Sky Computer Use native pipe closed before response`；重設 CUA kernel 並以相同 App 絕對路徑重新連接仍失敗。無法確認點擊後的畫面，不能據此判定 App 本身故障。
- 因無法繼續原生介面操作，7.1–7.5 保持未完成；8.3–8.5 亦尚未在本次驗收。未透過 GUI 提交轉錄、下載或移除模型；未主動停止使用者原有的背景服務。

## Initial task 5.6 investigation (superseded by follow-up above)

- 本次環境：macOS 26.6.2（25G83）、arm64，使用 Xcode 內建 Python；此環境不代表乾淨 Mac 或最低 macOS 14 驗收。
- 實際執行 `PYTHONPATH=src python3 -m unittest tests.desktop.test_evidence tests.test_longform -v`：**15 項測試通過**。涵蓋裝置證據資格、品質／時間戳未知時不得提升 GPU、資源門檻、環境身分隔離，以及長音訊分段、合併與 checkpoint 相容性。
- `evaluation/manifest.example.json` 的媒體路徑仍為範例；此 checkout 沒有 `evaluation/private/`、`build/` 或 `.venv`。既有文件引用的打包評測產物未包含於此 checkout。
- `/Applications/ASR Desktop.app` 與使用者的桌面資料目錄存在；本次未啟動、停止或修改既有服務與使用者資料，也未將其視為已校對的品質基線。
- 尚缺指定的中文／中英混合驗收音檔、人工校對逐字稿及時間戳標準答案。已詢問使用者本機路徑。未執行真實模型品質評測、完整 CLI／Drive adapter 回歸或長錄音資源驗收；不能以本次單元測試替代這些要求。
- 5.6 保持未勾選；本次沒有新增已完成任務。其餘驗收工作尚未在本次執行。

# Implementation progress — 2026-10-20

Overall **35/46 tasks complete**. Groups 1–4, 5.1–5.5, 6.2–6.5 and 8.1 are complete. Tasks 5.6, 6.1, 7.1–7.5 and 8.2–8.5 remain open. Do not archive this change yet.

Evidence and reproduction commands: [desktop/VALIDATION.md](../../../desktop/VALIDATION.md) and [desktop/README.md](../../../desktop/README.md).

## Confirmed implementation

- Native arm64 SwiftUI, CLI and helper targets build; 5 native tests and 121 source regression tests pass.
- Pinned Python 3.11.15/FunASR runtime freezes independently of the existing worker environment. Standalone FFmpeg/FFprobe have only system-library dependencies.
- Frozen-runtime imports, OpenCC and actual 16 kHz mono media normalization pass with developer PATH removed and invalid external Python paths set.
- Catalog pins four components to immutable commits and hashes. All 29 required assets have been verified in independent build-only snapshots.
- Eight real packaged CPU/MPS smoke cases pass for two models and Mandarin/mixed public examples, with nonempty text and valid timestamps.
- Shared immutable model preparation, SQLite jobs/events/settings, idempotent mutations, serial process-group workers, cancellation/recovery and protected TXT/SRT/JSON delivery are implemented and tested.
- Four real packaged Nano/Paraformer public-file batch jobs complete with all requested exports. Real control checks cover cancellation/retry, replay, observer interruption, calibration, partial failure and exit codes 0/1/2/3/130.
- The development image is built, checksum-verified, mounted read-only and tested after relocation. All 281 Mach-O files support arm64 and have no non-system absolute dependencies. No model weights are bundled.

## Blocking evidence

The staged ad-hoc-signed App passes strict signature verification, but SMAppService-managed launch is rejected by AMFI/launchd with `has no CMS blob?`, `Launch Constraint Violation`, and `OS_REASON_CODESIGNING`. This host has zero available Apple code-signing identities. Registration reporting enabled is not proof of a running service.

The user explicitly selected direct-helper development mode. Development App and CLI are visibly marked, service survives CLI and GUI exit, repeated starts use the same PID, and safe stop cleans up the socket. The formal profile rejects development launch. Task 1.5 is complete under that approved scope; managed-service acceptance remains pending in task 8.2. A second clean locked Python environment reproduced the frozen runtime/import/media smoke, completing 1.6. This does not substitute for a second Mac or minimum-OS acceptance. No operating-system protection was disabled; all test services were stopped.

The GUI with local private data visibly loads the same 12-job history (11 completed, 1 failed). Subsequent UI automation failed with `Sky Computer Use native pipe closed before response`; reset/rebind did not recover it. Full interaction acceptance stays unchecked. An iCloud data-root probe stalled in os_open; local data worked, and the precise cause remains unconfirmed. The product defaults to local Application Support. All test services were stopped.

Reviewed quality baselines are not established: real observations cannot promote auto GPU. Fresh-account/minimum-OS and representative long recordings remain unverified. Formal managed-service acceptance remains deferred under the user's explicit development-mode choice.

## GUI connection retry — 2026-10-20

At the user's request, CUA reconnected to the isolated development App and read the import-window accessibility tree. The development/paused labels, four tabs, import/output controls, model/device/script selectors and export checkboxes were visible. Preview and submit were correctly disabled with no selected input. Clicking Models then returned `Sky Computer Use native pipe closed before response`; the resulting tab state could not be verified. Kernel reset and exact-path rebind failed again. Inventory still worked, so the evidence identifies failed native App interaction rather than proving every tool surface is unavailable. The shared bundle identifier is ambiguous across installed/build/test copies; retrying the tool-reported `/tmp` test path also failed. No task in 7.1–7.5 is newly accepted. The App was relaunched during this retry; service shutdown has not been rechecked. Detailed evidence is in `build/desktop/gui-validation-evidence.json`. Formal signing remains deferred as instructed.

No Git commands, commits, tags, pushes or releases were performed. The current product remains under development; successful smoke cases do not establish macOS 14, long-recording performance, complete GUI/CLI parity, or formal-distribution acceptance.
