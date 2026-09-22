## Context

動機見 proposal.md。现有 `LocalTranscriptionService.run(JobConfig)` 提供本機轉錄、結構化進度、完成快取及長內容 checkpoint；目前沒有 Web、持久任務表或 Drive 整合。上次 MPS 成功案例不能視為目標 M4／16GB 的效能驗證。來源實測包含多層資料夾，根目錄不可新增子項目。

## Goals / Non-Goals

**Goals:** 同機部署、單一推論、可靠派送、重試可恢復、網頁可觀察、原生 MPS、金鑰留在 Mac。

**Non-Goals:** 多租戶、公開網際網路服務、多 GPU／多 Mac、模型跨任務常駐、即時串流、人工校訂、瀏覽器控制 launchctl、即時強制取消。第一版提供暫停領取與失敗重試，既有 CLI 不變。

## Decisions

### 1. Deployment boundary

```text
Browser -> Docker Web/FastAPI -> SQLite volume
                         | outbox dispatcher
                         v
                   Redis AOF volume <- RQ Dashboard
                         ^
Mac launchd -> RQ SpawnWorker x1 -> local ASR -> Drive delivery
Mac launchd -> lightweight scanner -> Drive listing -> API intake
```

Web 採 FastAPI 加伺服器渲染頁面及短週期輪詢，先不引入獨立 SPA 或 WebSocket。單一 API 程序存取 SQLite，啟用 WAL、busy timeout 與短交易。worker／scanner 僅透過 API 存取任務資料；不共用 SQLite 檔案。Redis 使用 AOF 和持久 volume。資料庫與 Redis 分別承擔業務紀錄及執行排隊，非互為完整備份。

容器內使用 Compose service name；Mac 連 loopback 映射埠。Web、Redis、Dashboard 預設只綁 127.0.0.1。管理登入、worker bearer token 與 Dashboard 存取控制分開；禁止任意命令／任意 RQ 函式由表單注入，佇列 payload 只含 JSON ID。若日後對 LAN 開放，必須另外配置 TLS 與網路存取政策。

選 RQ 而非自寫佇列是沿用現成 worker／重試／監控；選 SQLite 而非 PostgreSQL 是寫入量小且只有 API 開資料庫。Docker 不跑模型。API 與 worker 依賴分開鎖定，RQ 任務入口可共用但不得在 API 匯入模型套件。

### 2. Intake and scanning

使用者提交來源 folder ID／Drive folder URL、獨立目的地、模型、熱詞及字幕設定。預設 Fun-ASR-Nano、auto device、繁體輸出；設定在任務建立時快照。拒絕非 Drive URL，僅解析 ID，不任意抓取 URL。

建立掃描批次（pending/scanning/completed/blocked/failed）。原生 scanner 每幾秒領取掃描請求，與辨識分開；提供手動重新掃描以及可選週期監看，預設一次掃描。掃描請求也採執行 token、心跳與租約，避免重複掃描程序競爭。

遞迴讀完所有分頁，以 folder ID visited set 去重；跳過捷徑、垃圾桶與非媒體，排除整個目的地子樹及服務標記的結果。目的地等於來源或位於來源祖先時拒絕，避免排除整個輸入；允許不同樹或來源之下的專用結果子樹。第一版不跟隨捷徑，也不因来源删除而删除已交付結果。

來源只需可列出／下載；service-account 目的地必須有 shared-drive ID 且可新增子項目。預檢不建立測試檔；真實寫入仍需在驗收時測試。若目的地未通過，批次顯示 blocked，不啟動下載與 ASR。支援來源位於 My Drive、目的地位於 shared drive，處理 shared-drive API 參數。

檔案身份使用 Drive file ID，內容版本優先 checksum，否則 revision/version＋size；後者是保守失效策略，可能多建立候選但下載後可重用內容快取。下載前後重新讀 metadata，驗證 checksum 和來源版本；變更時丟棄不匹配暫存並重新掃描。純改名且 checksum 相同不重跑。

SQLite 唯一鍵包含來源 ID、內容身份、設定指紋與目的地 ID；批次用關聯表指向既有任務。掃描完成後按相對路徑自然排序建立穩定序號再派送，避免 API 分頁順序決定課程次序。部分掃描失敗保留候選但不發布該批次新任務。

### 3. Durable state and outbox

主要資料：sources/batches、batch_jobs、jobs、attempts、artifacts、outbox、worker_heartbeats、service_control。jobs 包含來源／目的地 ID、版本、設定快照、dispatch generation、目前 phase、next_retry_at、錯誤分類及本機 manifest 引用。實際私鑰與 token 不存資料庫。

API 在同一交易建立 job 與 outbox。單一 dispatcher 使用穩定 RQ job ID（job ID＋dispatch generation）派送後標記 sent；送出後回應遺失時查詢既有 RQ job，不能無條件新增。Redis 丟失佇列時，reconciler 對照業務終態、心跳及執行記錄補送安全候選；必要時建立新 dispatch generation。RQ finished 不直接等於業務 completed。

入列為至少一次，不宣稱 exactly-once。每次真正執行前必須由 API 原子批准 execution token；已完成、被較新 attempt 取代或已有有效執行者的任務拒絕重複開始。更新 phase 與終態都檢查 token。進度回報帶事件序號，舊事件不能覆蓋新狀態。

### 4. Execution and recovery

業務狀態：queued -> downloading -> transcribing -> uploading -> completed；另有 retry_wait、blocked、failed、interrupted。UI 將 retry_wait 顯示為等待重試，按 phase 保留已完成成果。scan 有獨立狀態，RQ 狀態作為診斷而非另一份業務真相。

一個 SpawnWorker 消費 asr queue；本機 supervisor 與任務執行鎖防止重複啟動，OS 鎖必須涵蓋仍存活的推論子程序生命週期。worker 啟動時先確認無殘存執行者，再恢復任務。模型在 spawned job 子程序初始化；透過既有 workflow callback 回報事件，不解析人類終端文字。獨立心跳執行緒不能被長時間模型呼叫阻塞，必須用真實模型驗證。若驗證無法維持心跳，改採控制程序監督新啟動的 ASR 子程序及結構化 IPC，並測試子程序清理。

初始心跳 15 秒、失聯門檻 90 秒，可配置。API／Redis 暫時失聯不立即啟動另一份推論；原任務可繼續本機計算並寫 checkpoint，但在重新確認 execution token 前不發布 Drive 結果。重啟後 reconcile 本機 manifest、API attempt 和 RQ registry，確認舊程序停止才重派。

RQ 使用有界 Retry 與 scheduler 支援延後重試，初始最多三次、60/300/900 秒退避；retry hook 同步業務狀態。API reconciler 僅在 RQ 排程不存在／遺失或人工重試時補送，不能與 RQ 同時建立兩份重試。網路／限流可重試，權限錯誤 blocked，媒體損毀 failed，未知錯誤保留診斷並有限重試。手動重試沿用同一業務任務、新 attempt。長任務 timeout 明確配置，初始上限六小時，不依賴短任務預設；逾時須清理整個執行樹。

暫停是停止領取新任務，當前任務完成後保持空閒；服務自有 wrapper 在領取前讀取持久 pause 狀態，重啟不遺失。暫停不停止只讀掃描。即時強制取消留待後續變更。

### 5. Outputs and publication

在本機 manifest 原子記錄階段與 artifact checksum。沿用既有 transcript／chunk cache；抽取共用 TXT 匯出功能，不依賴 outputs 中的單次腳本。TXT 採台灣繁體、保留內容與未校訂標記；SRT 保留既有時間驗證。

結果目錄採「來源檔名＋來源短 ID／內容與設定版本」，identity 以完整 ID／fingerprint 為準，不能靠顯示名稱判斷。產出 transcript.txt、subtitles.srt、completion.json，completion 記錄來源版本、模型／設定、校訂狀態與檔案校驗值。

新建 folder／binary artifact 先取得 Drive 預分配 ID，透過 API 存入 SQLite 並寫本機 manifest，持久化成功才 create。重試沿用 ID；遇到已存在確認 appProperties 身份及 checksum，內容不一致才更新。不以名稱搜尋當唯一防重複機制。共享 Drive 支援需在驗收確認。

completion.json 最後寫入；API 驗證已回報全部結果 ID 後才標記 completed。若上傳成功但回報遺失，重試檢查同一組 ID 後補回報。辨識已完成而上傳失敗僅重跑交付。目的地變更建立新交付身份，允許重用相容 ASR cache。

### 6. Operations and retention

Web 提供批次／任務列表、分階段進度、估計值標記、錯誤、結果連結、重試與全域暫停。worker 心跳与辨識進度分別顯示，離線不能冒充處理中。Dashboard 供診斷；不透過其管理操作繞過業務 API，部署時限制變更入口。

Mac launchd 初期採 LaunchAgent（登入後啟動），明確不承諾未登入開機即可執行；Docker Desktop 就緒與系統睡眠也是運行前提。要改 LaunchDaemon 必須另外驗證 MPS、憑證權限及 Docker 啟動方式。不自動改睡眠或登入設定。

本機工作根目錄在非同步 SSD 路徑，容量不足時停止下載並告警。未交付成果不得自動刪除；已完成暫存可在可配置保留期（預設七天）後清理。SQLite 用線上 backup API 或停機備份，Redis AOF 持久化與 outbox 補送共同恢復，仍需定期備份業務資料。

## Risks / Trade-offs

- SpawnWorker／目前 Python 3.9 與新套件／MPS 相容性 → 實作第一階段先做隔離 runtime spike，決定並固定受支援 Python（優先評估 3.11）和套件版本；不直接升級既有 venv。
- Redis＋SQLite 雙重狀態 → transactional outbox、token fencing、reconciliation 及故障注入測試。
- Drive 寫入無法和 SQLite 原子提交 → 預配置 ID、持久化上傳 manifest、內容確認與 completion marker。
- M4 16GB 與 Docker 共用記憶體 → 單工、任務結束釋放模型；實測 memory pressure／swap，不承諾既有機器耗時。
- 相同目錄名稱、來源變動、深層掃描 → ID／checksum 身份、visited set、範圍排除及穩定排序。
- 底層 dashboard 操作可能破壞业务狀態 → 維持業務 API 作唯一控制入口；監控工具存取受限。

## Migration Plan

1. 建立獨立服務環境，驗證 SpawnWorker／MPS；既有 CLI 保留可執行。

   使用者後續確認先在本機跑通：允許用目前 M1 Max／32GB 進行開發與 smoke test；不能將其資源數據視為 M4／16GB 驗收，後者仍由任務 7.4 追蹤。
2. 建立資料庫 schema migration、Compose volumes 及測試用憑證設定，不搬動真實來源。
3. 用 mocks 驗證派工、失敗與補送，再以明確選定的小型 Drive 測試來源／可寫目的地完成端到端驗收。
4. 安裝 LaunchAgent 前核對絕對路徑與登入前提；測試 Docker 延後啟動、Mac 程序重啟與恢復。
5. 回退時先暫停派工、等待目前任務結束，停止服務並備份 SQLite／Redis／本機 manifest；保留 Drive 已交付檔案與 CLI，不自動刪除資料。

## Open Questions

- 使用者已完成 OAuth 授權，並以兩段講座片段通過 My Drive 真實交付；M4／16GB 長音訊驗收仍待目標機器。
- 正式保留期和輪詢間隔可在上線時調整，不改變服務契約。

### 7. User OAuth for My Drive destinations

使用者提供的目的地 `test` 不在 shared drive，因此依其提供的 Desktop OAuth client 加入 `ASR_DRIVE_AUTH=oauth`；預設仍為 `service_account`。OAuth 使用者可對有 canAddChildren 的 My Drive／shared drive 資料夾交付；服務帳號仍必須使用 shared drive，不以放寬共同預檢繞過儲存限制。

首次登入是 native CLI 的 loopback + PKCE 流程，使用者親自完成 Google 同意。為遞迴掃描任意既有資料夾，本版申請 Drive scope；尚無 Picker，不宣稱 drive.file 能讀取全部既有來源。Token 以原子檔案、600 權限保存於非同步本機設定目錄；client JSON、refresh token 不進入 Docker／SQLite／Redis。兩個 native 程序讀取同一授權檔，在記憶體中自動更新 access token，避免並發寫回互相覆盖。授權撤銷時顯示 blocked，重新執行登入；不自動切換帳號。

若 Google OAuth consent screen 為 External/Testing，Drive refresh token 通常七天到期；長期運行前需處理測試使用者及發布設定。首次登入完成不等同於實際 Drive 上傳驗收。
