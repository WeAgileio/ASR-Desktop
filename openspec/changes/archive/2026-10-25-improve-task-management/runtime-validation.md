# 任務管理驗證紀錄

日期：2026-10-24（Asia/Taipei）。本次先依使用者確認修正設計：`counts` 保留既有批次範圍統計，不受新增文字／狀態條件影響。

## 已執行

- Python 3.11.15，macOS arm64；`PYTHONPATH=src build/desktop/packaging-env/bin/python -m unittest discover -s tests/desktop -q`：73 項通過。測試資料皆位於隔離暫存目錄。
- `build/desktop/packaging-env/bin/python desktop/scripts/build_app.py --test --scratch-path /private/tmp/asr-task-management-swift`：10 項 Swift Testing 通過。
- `build/desktop/packaging-env/bin/python desktop/scripts/build_app.py --scratch-path /private/tmp/asr-task-management-swift`：原生 App 建置通過。
- 兩個批次、240 筆混合狀態資料的搜尋／分頁／統計與 token 測試通過；100 次篩選列表查詢耗時 0.1040 秒，平均 1.040 毫秒。這是本機小型測試資料量的觀察，不是延遲保證。
- 受控 worker 測試通過：確認後開始執行、取消中仍有子程序、完成回收後再移除，以及後續 FIFO 單工處理。
- 真實 WAV 與含影像及音軌的 MP4 由開發環境 FFmpeg 產生，以 App 內建 FFprobe 探測通過；App 精簡版 FFmpeg 沒有 lavfi／MP4 編碼用途，測試素材產生不使用它。
- 背景探測工作數上限、慢探測期間 queue.pause 可回應、無任務建立、來源不做完整雜湊、逐檔失敗、符號連結與重疊來源排除均有自動測試。
- 成果摘要測試涵蓋 committed、prepared、部分交付、已遺失、舊成功任務及損壞 ledger；列表搜尋不載入成果摘要。
- Finder 以替代呼叫測試檔案 URL、中文／空白／巢狀、多格式、路徑遺失與開啟失敗；這不代替真正 Finder GUI 驗收。

## GUI 驗收（2026-10-25）

使用者解鎖後，以 CUA 實際操作隔離 App；先前鎖定阻礙已解除。測試 workspace 為 `/private/tmp/asr-management-gui-9c0lkurj`，資料、快取、輸出及 socket 與使用者正式資料分開。最新驗收 App 為 `/private/tmp/asr-desktop-dev-n8yq74hf/ASR Desktop.app`，已 ad-hoc 簽署並通過 deep/strict 驗證；報告見 `build/desktop/task-management-signing.json`。

### 實際觀察

- **G1 批次與改名**：兩個同預設名稱批次各 120 筆，均可獨立選取；空白名稱顯示 0/100 且不能儲存，取消改名保留原名。保存「十月訪談 GUI」後重新整理及退出／重開 App，名稱與 120 筆歸屬保持。
- **G2 搜尋與多選**：在 120 筆批次搜尋 `119`，找到原第二頁檔案，範圍 120、符合 1；不存在字串顯示空結果提示及 0–0。失敗與取消多選取聯集 60 筆。第一頁勾一筆後到 101–120 仍顯示已選 1；全選顯示 120，回第一頁仍保留。更改搜尋清空選取；另一客戶端重試其中一個失敗任務後，符合結果 60→59、全選失效並提示重新選取。
- **G3 重試**：搜尋 `119` 僅顯示兩筆時，批次失敗重試仍處理整批 20 筆失敗、略過 100，取消／中斷未被帶入。明確勾兩個取消任務重試，結果為 2、略過 0。新影片任務取消後按單筆重試，結果為 1、略過 0。因隔離環境未備模型，重試後為 blocked；未跑模型辨識。
- **G4 移除**：單筆已完成任務預覽顯示 1 筆及完整保留檔案／失去入口／不清理快取／不可復原文案；取消不變，確認後 240→239，詳情清空。另一批在第二頁全選 120 後移除，空批次消失、總數 119、回 1–100 且選取清空。新批整批入口確認顯示名稱與 121 筆，取消後仍為 121。單筆影片移除確認開啟後，另一客戶端取消任務；舊確認被 `Targets changed; refresh selection and confirm again` 拒絕，總數仍 240。重新確認後可移除，總數 239。另以暫存資料庫注入 running 狀態驗證 GUI 預覽阻擋及「請先停止並等待」提示，隨即還原 cancelled；真實程序回收競爭由受控 worker 測試驗證，沒有將注入狀態稱為真實執行。
- **G5 時長與提交**：未選輸出目錄時加入混合資料夾，真實 WAV、MP4 各顯示 0:01，無效文字檔個別顯示 FFprobe 錯誤；遞迴切換後 nested.wav 出現。讀取中可操作 JSON 與輸出選擇器。121 檔讀取期間清除後舊資料未再出現，重新加入重新讀取。選輸出後正式預覽顯示可提交 121，按提交後顯示接受 121。新批包含 120 WAV 與 1 影片；列表與詳情均顯示保存時長。重開後仍有新批 120、舊批 119；239 筆任務保存 duration_ms=1250。
- **G6 Finder**：中文空白檔名 WAV 及 `GUI video.mp4` 均開正確 input 位置並選取 1 檔。已交付 TXT／SRT／JSON 開啟實際 `outputs/0` 子資料夾並選取 3 檔；prepared JSON 與搬移 SRT 的測試狀態下，只選取已交付且存在的 TXT，詳情分別顯示未交付及已遺失。來源暫時搬移後，顯示「路徑不存在，檔案可能已搬移或刪除。」；新影片未產生成果時顯示「尚無已交付成果。」。測試後已還原搬移的檔案與 ledger。
- **G7 檔案保留與重開**：初次紀錄移除前後 127 個檔案 SHA-256 相同；最後一次移除前後 132 個來源／成果／ledger／快取檔案 SHA-256 相同（包含刻意加入的 cache marker）。manifest 為隔離根目錄下 `files-before.json`、`files-final-before.json`。App 重開後仍為兩批 120+119，已移除的兩個單筆 ID 不在資料庫中；來源及成果檔案仍在。移除前一致性資料庫備份為 `before-gui-removal.sqlite3`。

### 驗收中修正與回歸

- 定時刷新即使內容未變也發布列表，導致右鍵選單消失；改為內容不同才發布 jobs／batches，實際重試及改名選單已可完成。
- 匯入來源列與探測列共用整數身份造成重複／缺漏；來源列改用 URL 身份，混合資料夾與 121 筆資料重測通過。
- 修正後原生 App 重新建置、封裝及簽署成功。`build/desktop/packaging-env/bin/python desktop/scripts/build_app.py --test --scratch-path /private/tmp/asr-task-management-swift`：Core 10 項、App 1 項，共 11 項通過。新增 `selectionSurvivesPagingButNotNewConditions` 直接測實際 DesktopModel 的跨頁選取、全選 120、條件／批次切換清空與回第一頁，不啟動服務。
- Python 最終回歸仍為本變更已執行的 73 項通過（5.564 秒）；本輪 GUI 修正沒有更動 Python。原生 CLI list/show/retry/cancel/watch／重送已通過，watch 對 cancelled 回傳預期退出碼 1，見 `build/desktop/task-management-cli-validation.json`。

### 規格情境對照

以下涵蓋 delta spec 全部 34 個情境。測試名稱位於 `tests/desktop/`，Swift 測試位於 `desktop/Tests/`；G 編號對應上方實際觀察。

| 規格情境 | 證據 |
| --- | --- |
| 提交前多次加入來源；再次提交相同來源；開啟既有任務資料 | `test_preview_deduplicates_roots_excludes_symlinks_and_invalid_media`、`test_request_replay_and_atomic_rollback`、`test_old_schema_names_pagination_and_counts`；G1、G5 |
| 加入檔案後直接取得時長；資料夾內包含可讀與無效媒體 | `test_real_audio_and_video`、`test_discovery_and_individual_failures_without_hashing`、`test_probe_validation_and_background_controls`、`durationsAndQueryGenerations`；G5 |
| 清除來源後探測才完成；提交後重新開啟任務 | G5、G7；檢查來源與遞迴 onChange 才呼叫 inspectSources，清除會遞增 generation 並取消舊 task；正式 preview／submit 沿用 intake 驗證，列表／詳情只讀保存數值 |
| 批次改名成功；名稱無效或使用者取消 | `test_rename_replay_validation_and_persistence`；G1 |
| 符合任務不在目前分頁；搜尋批次名稱並限制失敗狀態；搜尋特殊字元；清除條件或沒有結果 | `test_full_range_literal_search_and_counts`；G2 |
| 全選跨頁結果；切換批次或條件；延遲回應抵達；移除最後一頁的任務 | `selectionSurvivesPagingButNotNewConditions`、`durationsAndQueryGenerations`、`test_selection_is_read_only_and_tokens_track_membership_and_state`；G2、G4 |
| 批次具有混合狀態；批次操作遇到畫面篩選；選取中包含不可重試狀態；重試前來源改變 | `test_retry_scope_atomicity_and_replay`、`retryIdentityAndTimeout`；G3 |
| 確認移除整批；確認移除選取項目 | G4 |
| 等待中的任務被移除；任務於確認期間開始執行；移除已停止的歷史任務；批次被清空；重送已成功的移除請求 | `test_remove_atomic_replay_and_files_preserved`、`test_remove_requires_reaped_group_and_reconfirmation`、`test_submission_replay_does_not_restore_removed_rows`；G4、G7 |
| 定位中文或空白路徑的原始檔；成果位於輸出根目錄下的子資料夾；部分成果已交付；尚無成果或路徑已遺失 | `finderUsesFileURLsAndRejectsMissingPaths`、`test_committed_partial_missing_and_legacy`；G6 |
| 舊客戶端使用原有重試方式；移除後重開視窗或重播事件 | CLI validation、`test_retry_scope_atomicity_and_replay`、`test_submission_replay_does_not_restore_removed_rows`；G7 |

### 驗證邊界

實際 GUI 使用選檔／資料夾入口；拖放入口以程式碼核對其更新相同 sources 並觸發同一檢查，未另做跨視窗拖曳手勢。Finder 開啟失敗以替代呼叫測試，未故意破壞系統 Finder。模型辨識品質、正式簽署／公證與安裝更新不屬本變更驗收，沒有藉此勾選原桌面變更任務。臨時注入的執行中狀態、部分交付 ledger 與合成媒體已明確區別於真實 worker／模型成果。

初次沙箱內 Swift 建置與程序列表檢查受到限制，升級工具執行後通過。沒有執行 Git 指令、發布或替換 `/Applications` 的正式 App。

最終規格檢查：`openspec validate improve-task-management --strict` 通過；此結果只驗證規格結構，產品行為依上述測試與 GUI 證據判定。
