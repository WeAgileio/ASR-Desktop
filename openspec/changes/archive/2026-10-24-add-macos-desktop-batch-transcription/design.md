# Design

## Context

動機與產品範圍見 [proposal.md](proposal.md)。使用者已確認：Apple Silicon、獨立桌面視窗與完整 CLI、錄製檔案批次轉錄、TXT／SRT、安裝後下載模型，以及有證據的自動／CPU／GPU 選擇。

現有 `LocalTranscriptionService` 可重用：媒體處理、兩個 FunASR adapter、共同 transcript、分段 checkpoint、字幕與獨立進度事件均已存在。`asr-srt` 是同步單檔 CLI；TXT 匯出目前位於 `asr_service.outputs`。既有 Drive 服務使用獨立的 SQLite／Redis／RQ，不適合成為桌面版的必要依賴。

現有裝置策略在缺少可比較的長內容資料時優先選 MPS。效能 key 缺少完整機型／PyTorch／OS 身分；資源快照只取得程序 RSS，沒有真正填入 memory pressure 與 swap。模型 adapter 使用 `master`，模型快取存在兩個檔案也不等於完整離線資產。這些都需在桌面版交付前補齊，不能引用現有短片評測宣稱已完成驗收。

以下技術選擇與數值是本提案的工程預設，可依實測修正並同步規格；它們不是使用者另外指定的要求。

## Goals / Non-Goals

**Goals:**

- 任務、模型與推論核心只有一份權威狀態，GUI／CLI 是同等客戶端。
- 用程序隔離控制推論資源、故障與取消；保存可重用的已完成工作。
- 完整管理模型資產與執行依賴，使已就緒模型能在封鎖網路的環境轉錄。
- 裝置策略可解釋、可測試，沒有有效證據時保持保守。
- 打包與真實長音訊驗收是交付條件，不以開發環境可執行代替。

**Non-Goals:**

- 不重寫 ASR 模型、字幕編輯器、Drive 服務或既有單檔 CLI。
- 不加入多檔平行推論、任意第三方模型載入、自動雲端備援或登入後自動開始未完成批次。
- 第一版採直接下載的 App／DMG，不包含 Mac App Store 上架與自動更新服務。

## Decisions

### 1. SwiftUI 視窗、Swift CLI 與內建 Python runtime

工作名稱為 **ASR Desktop**，新增命令 `asr-desktop`，不占用既有 `asr-srt`。目標為 arm64、macOS 14+；最低版本必須在對應系統驗證，未驗證不得宣稱支援。選 SwiftUI 是因為只做 Mac，便於原生檔案選擇與背景服務管理。Tauri 可用，但本案沒有跨平台需求，不額外引入網頁／Rust UI 工具鏈；純 Python GUI 雖可減少語言數，仍需要額外處理同樣的 Mac 發行整合。

Python 推論與協調程序採 PyInstaller onedir 收集後納入 App 的受簽署 helper bundle，固定 Python 3.11 與經驗證的 arm64 依賴；具體版本由打包驗證產生 lock。FFmpeg／ffprobe 使用內建絕對路徑。啟動時不得依賴 shell PATH、系統 Python、Homebrew 或首次使用時 pip 安裝。選 onedir 避免每次推論展開大型 runtime。若套件收集不完整，修復打包 hook 或固定依賴，不把安裝責任轉交使用者。

模型權重不放進安裝檔。模型所需的 Python 程式、tokenizer 套件與其他執行依賴必須已包含於 App；模型下載不得執行任意安裝腳本。初始模型選擇沿用 `fun-asr-nano`，並提供 `paraformer`，兩者須通過各自的發行驗收。

### 2. 一個使用者層級的協調程序

```text
SwiftUI App ─┐
             ├─ 版本化本機協定 ─ 本機協調程序 ─ SQLite 任務／事件／設定
Swift CLI ───┘                      │
                                   ├─ 模型下載與驗證
                                   └─ 一個推論子程序
                                         └─ asr_srt 核心 → TXT／SRT／JSON
```

正式建置採使用者層級 LaunchAgent 管理協調程序，透過內建的 Swift 啟動橋接與 `SMAppService` 註冊。首次 GUI 或 CLI 需要服務時均可啟動，不要求先開啟視窗、不使用 root。系統若要求啟用背景項目，兩個入口都回報相同狀態與處理方式，不能回報服務已就緒。服務的啟停不等於佇列恢復；登入／重開機後即使 helper 啟動，也保持待恢復狀態直到使用者操作。

2026-10-19 實作驗證確認此機器的 ad-hoc helper 被 AMFI 的啟動約束拒絕。使用者明確選擇先以開發模式繼續：開發 profile 的 App 直接以相同使用者身分啟動 helper，helper 脫離客戶端終端工作階段，stdio 接至私有日誌，GUI／CLI 都明確顯示 `development` 模式。此路徑僅限明確的開發建置；正式建置在 SMAppService 失敗時仍回報未就緒，不自動降級。正式簽署與 managed lifecycle 驗收移至 8.2／8.3，不因開發模式成功而勾選。

關閉視窗或 CLI 客戶端不停止已接受的任務。明確停止服務時先暫停領取，預設等待目前任務完成；強制停止走同一取消與回收流程。閒置時保留輕量協調程序，不保留已無任務的模型。第一版每個檔案建立一個推論子程序，檔案內的長音訊分段沿用單一模型 session；跨檔暖模型是後續優化。

協調程序與客戶端使用私有 Unix domain socket，socket 父目錄 0700、socket 0600，檢查 owner、拒絕符號連結與其他使用者連線。使用短路徑避免 macOS socket 路徑上限。無 HTTP 監聽埠。SQLite 僅由協調程序寫入；GUI／CLI 不直接改資料庫。相較於直接執行 CLI 子程序，這個方案能支援跨入口控制與視窗關閉後執行；相較於 Redis／RQ，少一組安裝與常駐依賴。

### 3. 持久化資料與任務生命週期

資料根目錄為 `~/Library/Application Support/ASR Desktop/`，包含 SQLite、不可變模型 snapshot、模型目錄與可恢復 checkpoints。可重建音訊置於 `~/Library/Caches/ASR Desktop/`，日誌置於使用者 Logs 目錄。App 更新不得清除上述資料。桌面版不共用舊 CLI／Drive 的可寫 cache，避免跨程序搶寫；匯出檔位於使用者指定目錄。

資料分為 batches、jobs、attempts、events、model_snapshots、download_tasks、device_profiles 與 settings。每筆任務保存來源指紋、固定辨識／輸出設定、模型 snapshot ID、已規劃的輸出路徑與目前 attempt。全域單工領取以協調程序單例鎖和資料庫交易保護；每個 attempt 使用獨立識別碼，過期子程序事件不可更新新 attempt。

```text
blocked(model) → queued → running → completed
                          ├──────→ failed
                          ├→ cancelling → cancelled
                          └──────→ interrupted

failed / cancelled / interrupted --明確 retry--> 新 attempt
```

`blocked` 是缺少指定模型的可見狀態，不占推論槽，也不自動觸發下載。模型就緒後可入列；後面已就緒任務可先執行。佇列 pause 是獨立持久化旗標，只停止新領取，當前任務繼續。取消 queued／blocked 任務立即生效；running 任務先請求協作停止，在 5 秒內未停止則終止該 attempt 的程序群組，再於 5 秒後強制回收。取消完成前不領取下一檔，不將未完成的 chunk 當 checkpoint。

協調程序或 worker 意外退出時，先確認並回收舊 attempt 子程序，再將未確定完成的任務標為 interrupted，暫停領取並要求使用者恢復；重開機亦同。一般單檔失敗則記錄原因後繼續其他任務。retry 重驗來源、模型、checkpoint 與輸出；來源內容改變時拒絕沿用原任務，需重新提交。

### 4. 批次匯入與結果交付

GUI 可多選／拖入檔案或資料夾；CLI 使用 `submit PATH... --output-dir DIR`，遞迴掃描需 `--recursive` 或 GUI 勾選。第一版不追蹤符號連結與持續變動的資料夾。掃描結果顯示可處理、重複、無效與不支援項目；以 FFprobe 驗證媒體，不只依副檔名。同批重疊資料夾以正規化來源路徑去重。來源提交時與執行前核對內容指紋，原始檔不修改。

新批次明確指定可寫輸出根目錄，GUI 可記住上次位置。資料夾輸入保留相對結構；多個來源根目錄及相同 stem 衝突時加入穩定來源識別後綴，完整輸出計畫在提交前可預覽並固定。跨批次遇到已有輸出預設將該檔標記 output_conflict，其他檔案繼續；只有明確指定 overwrite 才能替換。任何來源與輸出實體路徑相同都拒絕，即使 overwrite 也不例外。

預設 TXT + SRT、台灣繁體；可選原文與 JSON。TXT 匯出抽到共用核心，從未改寫的 transcript 產生文字；SRT 沿用既有切句規格。匯出使用與目標同檔案系統的暫存檔、逐檔原子提交與輸出 manifest。只有所有要求格式均校驗完成後才將任務標 completed。中途磁碟滿或程序退出時保留轉錄快取及已交付檔案的 checksum ledger，重試只補缺失結果；無法確認屬於同一任務有效輸出紀錄的既有檔案一律當成衝突，不能盲目覆寫。此處不宣稱多個檔案可由檔案系統同時原子提交。

### 5. 安裝後下載且可離線驗證的模型

App 隨附版本化模型 catalog，列出兩個支援模型的固定 revision、所有 ASR／VAD／標點／tokenizer／設定資產、大小、SHA-256 與來源。模型清單必須在發行建置時產生並驗證，不能用 `master` 或浮動 URL 當版本身分。第一版不加入遠端自動更新 catalog；新 catalog 隨 App 版本交付。

首次使用展示模型、下載量、所需空間及狀態，由使用者開始下載；CLI 有相同命令。下載至 staging，保存已驗證檔案與可續傳 partial。只有伺服器支援 Range 且資產身分未變時續接該檔案，否則重抓該檔案並保留其他已完成檔。檢查下載與組裝峰值所需空間，校驗所有資產後原子發布為 ready snapshot。下載失敗不發布、不自動改選另一模型。

任務建立時固定 snapshot，包括尚未下載的目標 snapshot。新增模型版本不改變既有任務；執行中或待執行任務引用的 snapshot 禁止刪除。移除前清楚列出占用，完成／取消等歷史任務不永久阻擋刪除，但 retry 必須重新取得原 snapshot。只有已就緒的本機路徑可交給推論器；推論期間關閉更新查詢、hub fallback 及隱式下載。真正離線驗收必須在禁止外連時完成解碼、辨識和匯出。

### 6. 自動裝置選擇與證據的適用範圍

新 GUI 顯示「自動／CPU／GPU」，新 CLI 接受 `auto|cpu|gpu` 並兼容 `mps` 別名；核心記錄 `cpu|mps`。既有 `asr-srt --device mps` 保持有效。明確 CPU／GPU 不受效能資料覆寫；GPU 失敗回報錯誤，自動模式才允許已辨識的 MPS 相容性失敗退回 CPU 一次。媒體錯誤、磁碟滿或任意未知例外不當成 GPU 相容性問題。

政策先適用於同一份共用核心，因此既有單檔與 Drive 呼叫者也須跑回歸。沒有有效證據時選 CPU 並記錄 reason=insufficient_evidence。自動模式不會為蒐集資料偷偷把使用者整份檔案重跑兩遍。GUI／CLI 提供明確啟動的 calibration：使用同一份本機短樣本測兩種裝置，樣本不外傳；結果只對適用的時長區間有效。校準作為有獨立 ID 的控制任務，使用相同單工槽、pause 與取消機制，兩種裝置依序執行，不與轉錄爭用推論資源。

證據 key 包含硬體型號、RAM 容量、OS 版本、App 推論政策版本、Python／FunASR／torch／torchaudio、不可變模型及輔助資產版本、device、辨識設定、冷／暖載入策略與時長區間（小於 10 分鐘、10–60 分鐘、超過 60 分鐘）。舊 profile 缺少必要欄位時只保留為歷史，不參與選擇。

採樣只納入成功、未命中 transcript cache、未 resume 且至少 30 秒的完整實際推論；模型載入與 ASR 分別記錄，決策比較與當前冷／暖策略相符的模型載入加推論成本。每種裝置至少三筆有效可比較樣本，使用中位數；MPS 至少快 10% 且通過品質／時間戳基線及資源門檻才自動升級，否則維持 CPU。不是依不同來源的單次快慢就切換。

資源門檻預設為 worker peak RSS 不超過實體 RAM 的 70%、memory pressure 保持正常、無持續超過 64 MiB 的系統 swap 增長（至少兩次相隔 5 秒觀測）。記錄門檻版本、取樣來源與系統背景負載。RSS 不等於完整 GPU 統一記憶體，必須搭配壓力觀測；量測不可得時標 unknown，該樣本不具有自動升級 GPU 的資格，但不阻止使用者明確指定裝置完成任務。系統其他程序造成壓力會保守排除樣本。

相容性／品質基線由發行驗收的已知語料建立；一般使用者任務只能補充成功率與耗時，不能冒充有標準答案的品質驗證。短樣本 calibration 不授權長音訊升級 GPU。已知 MPS 失敗後使該精確組合的 GPU 自動選擇失效，直到明確重新校準通過；重試針對 CPU 相容 checkpoint，不能混用不相容的 GPU 分段。

### 7. CLI 與通訊契約

Swift GUI 與 CLI 共用協定 client；以 NDJSON 傳輸 request ID、protocol version、操作與結果。服務回應包含 job／batch ID、狀態、錯誤碼與事件序號。事件可從 cursor 重播；客戶端落後超過保留視窗時回傳最新 snapshot 與 reset 指示，不丟失權威任務狀態。高頻進度可合併，生命週期事件必須持久化。

具副作用的請求將 request ID、內容摘要與結果在同一交易中持久化；相同 ID／內容重送回傳原結果，相同 ID 搭配不同內容則拒絕。這避免回應遺失後的重送產生第二批任務或第二次 retry。

命令族如下，具體 help 作為公開契約測試：

| 命令 | 功能 |
| --- | --- |
| `submit PATH... --output-dir DIR [--recursive] [--wait]` | 驗證並提交批次；預設回傳 ID，wait 等待結果 |
| `jobs list / show ID / watch ID / cancel ID / retry ID` | 任務與批次狀態、事件及控制；ID 型別可辨別 |
| `queue pause / resume` | 暫停或恢復新領取 |
| `models list / download ID / verify ID / remove ID` | 同一 catalog 與 snapshot 管理 |
| `settings show / set` | 模型、裝置、輸出格式、字幕與繁簡預設；僅影響新任務 |
| `device explain / calibrate` | 決策依據與明確的本機校準 |
| `service status / start / stop`、`diagnose` | 背景程序與內建依賴診斷 |

一般命令提供 `--json`，watch 提供 NDJSON；stdout 僅放結果／事件，stderr 放診斷，不混入依賴套件日誌。退出碼：0=操作成功或 wait 全部成功、1=任務失敗／取消／輸出衝突、2=參數錯誤、3=服務／模型／權限等前置條件未就緒、130=使用者中斷客戶端觀察。非 wait 的成功提交不表示轉錄完成；`--wait` 遇 blocked 或 interrupted 回報 3 及 ID，避免永遠等待人工作業。Ctrl-C 停止觀察但不取消已提交任務，取消需明確命令。

App 內含可直接以絕對路徑呼叫的 CLI，另提供 GUI 按鈕與 `cli install` 在 `~/.local/bin` 建立連結，遇到其他同名程式拒絕覆寫；不暗改 shell 設定。可用完整路徑或明確提示 PATH 設定，無需安裝額外 runtime。協定不相容時停止提交並引導使用相同版本，不讓新客戶端寫入舊版狀態。

### 8. 桌面視圖與可觀測狀態

主要視圖為批次清單、任務詳情、模型管理與設定。任務詳情顯示來源、輸出位置、選定模型／版本、要求與實際裝置、決策／fallback 原因、階段、elapsed、可信的 estimated ETA，以及錯誤與重試入口。批次以成功／失敗／取消／待處理檔案數呈現，不把檔案數百分比當成運算時長百分比。

模型下載進度與轉錄進度分開。沿用既有 actual／estimated／indeterminate 意義，沒有可靠 ETA 時只顯示階段與時間。設定變更只影響新任務；既有任務依提交時的設定與模型 snapshot 執行。GUI 使用者可完成 CLI 的所有日常功能，包括背景服務、模型移除、診斷與校準。

## Risks / Trade-offs

- [Python／PyTorch bundle 大且動態依賴容易遺漏] → 先做乾淨環境封裝驗證，再擴充 UI；依賴全部固定，發行前禁止外連測試。
- [原生背景權限或檔案存取受 macOS 限制] → GUI／CLI 共用 readiness 與錯誤狀態，測試使用者拒絕後的恢復，不以 root 或關閉系統防護繞過。
- [每檔重新載入模型增加小檔延遲] → 第一版換取可預測的資源釋放；效能計入載入成本，不假稱暖載入速度。
- [CPU 保守預設可能低於可用 GPU 速度] → 顯示選擇原因、提供手動 GPU 與校準，達標後才自動採用。
- [取消會丟失目前未完成 chunk] → 明確告知保存粒度；已提交 checkpoint 不受影響，不宣稱任意位置即時續跑。
- [輸出跨多檔無單一原子交易] → staging、checksum ledger 與明確任務完成條件，失敗可只重試輸出。
- [簽署與 notarization 需要開發者身分] → 開發包可本機驗證，但正式分發必須完成簽署／公證與乾淨機驗收；憑證缺失時明確標記發布未完成，不要求使用者停用 Gatekeeper。

## Migration Plan

1. 先建立內建 runtime、模型固定版本與離線 smoke 的可行性證據；不改現有 Drive 部署資料。
2. 將 TXT 匯出、明確模型路徑、取消與裝置政策做成核心介面，對既有 CLI／Drive 呼叫跑回歸。
3. 新建桌面資料根目錄與有版本的資料庫，交付協調程序及 CLI，再接 SwiftUI。資料庫升級前備份；舊程式讀到較新 schema 應拒絕啟動，不破壞資料。
4. 使用乾淨 arm64 帳號／機器驗證安裝、下載、離線、GUI／CLI 互控、長音訊、取消與重啟；macOS 14 最低版本另行實測。
5. 更新 README 使用方式與對應版本 Release Notes。提案及實作不自動授權發版，Git／版本／遠端確認仍遵守專案規則。
6. 更新 App 前暫停新領取並完成或取消目前工作，再替換 bundle 與重連 helper。回退 App 時保留模型與輸出；若 schema 不相容，用升級前備份恢復資料庫，不能直接讓舊版修改新 schema。

## References

- [Apple SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice)：macOS 13 起的使用者 helper 註冊與管理 API；實際權限狀態需在打包 App 驗證。
- [PyInstaller usage](https://pyinstaller.org/en/stable/usage.html)：onedir 收集與 macOS 簽署選項；不代表 FunASR 動態依賴已自動收齊。
- [FunASR installation](https://github.com/modelscope/FunASR/blob/main/docs/installation/installation.md)：arm64 一致性、完整模型資產及離線驗證的依據。
- 專案現況：`src/asr_srt/workflow.py`、`device.py`、`performance.py`、`adapters/local_models.py`、`src/asr_service/outputs.py` 與 `evaluation/RESULTS.md`。
