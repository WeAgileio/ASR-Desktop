## Context

主要素材長達兩小時以上。現有 workflow 對整份 WAV 呼叫一次 adapter，adapter 在 `transcribe()` 內建立 FunASR `AutoModel`，成功回傳完整 Transcript 後才寫入 cache。對短素材，Nano 實測約 25 秒花在載入模型；但對兩小時素材，單次載入占比很低，ASR RTF、記憶體／swap 與失敗後重跑才是主要成本。

目前 Nano 短素材 CPU inference RTF 約 0.637，MPS 約 1.53，不能安全外推長素材；Paraformer 的本機 CPU/MPS 矩陣仍缺資料。`auto` 現在只依 MPS availability 選擇 device，沒有長內容效能證據。既有 transcript cache、structured progress、RTF profile 與全域 segment estimate 可作為基礎，但都只處理單次完整 adapter call。

## Goals / Non-Goals

**Goals:**

- 對兩小時以上素材提供可比較的 stage timing、RTF、記憶體與穩定性基線。
- 將長素材拆成 deterministic、silence-aware 的頂層 chunks，逐段原子 checkpoint 並可恢復。
- 在同一長任務內只載入一次模型，順序處理所有 pending chunks。
- 保留完整全域 timestamps、文字、hotwords、cache identity 與既有 SRT 輸出語義。
- 讓 auto device 只在有相容長內容證據時做 profile-aware 選擇。

**Non-Goals:**

- 不同時平行執行多個 Nano／Paraformer model sessions。
- 不自動下載缺少的模型或私有評測素材。
- 不因追求速度而接受 plain-text-only、缺少 timestamps 的替代 runtime。
- 不在本 change 導入跨機器工作佇列、分散式 inference 或 GUI。
- 不保證所有兩小時素材都達到固定 RTF；驗收以相同素材與 runtime 的基線比較。

## Decisions

### 1. 先分離計時，再改變執行策略

新增 renderer-independent performance spans：audio extraction 之外，至少分離 model load、silence scan／chunk planning、per-chunk ASR、normalization、checkpoint I/O、merge 與總 transcription wall time。評測額外記錄 peak RSS；memory pressure／swap 以平台支援時才記錄，缺失不得影響任務。

Performance profile 區分短任務 ETA 樣本與 long-form device evidence，後者至少以 model id/revision、runtime、device、長度級距、chunk-plan version 與主要 batch/VAD 參數分組。避免用 5 秒音訊的固定 overhead 決定兩小時 device。

### 2. 長內容使用 silence-aware 頂層 chunk plan

預設只對超過 long-form threshold 的音訊建立 chunk plan；初始建議 target 20 分鐘、允許範圍 15–30 分鐘、在目標點前後最多 60 秒搜尋靜音。具體數值集中在版本化 planner settings，未來可用 benchmark 調整。

planner 在已抽出的 mono 16 kHz WAV 上使用可測試的 silence detector，將候選 interval 正規化後依固定規則選擇最接近目標、足夠長的靜音中點。所有 chunk boundaries 使用整數毫秒，plan 必須覆蓋 `[0, duration]` 且不可出現未規劃的 gap。

若找不到靜音，使用固定 boundary 並加入小型 bounded overlap。沒有選擇完全硬切且無 overlap，因為可能切斷連續語音；沒有先重寫 FunASR VAD，因為那會耦合私有調度並擴大模型回歸風險。

### 3. 每個 job 建立一個 model session

將 adapter lifecycle 分成 `open_session(device/settings)` 與 session-level `transcribe_chunk(request)`。workflow 在讀取 checkpoints 後才建立 session；若所有 chunks 已完成則完全不載入模型。Pending chunks 按時間順序執行，共用同一 model instance，以免頂層切分反而重複支付載入成本。

session 只在一個 job／device attempt 內共享，不建立跨程序 daemon。MPS compatibility fallback 關閉 MPS session，建立 CPU session，並沿用只有在 CPU-compatible identity 下仍有效的 checkpoints；device-specific output 未被證明等價前，不跨 device 冒用 checkpoint。

### 4. Checkpoint 與 completed transcript 分層

completed transcript cache 保持現有 contract。另建立版本化 long-form manifest，記錄 source fingerprint、duration、audio preprocessing identity、planner settings/version、完整 chunk boundaries、model/revision、device compatibility、language、hotwords 與 recognition settings。

每個 chunk checkpoint 包含 plan identity、chunk index/boundaries、local normalized Transcript、processing metadata 與內容 checksum，以原子 replace 寫入。Manifest 或 checkpoint 損毀、缺失、重複、越界或 identity 不符時，只使相應 chunk 失效，不刪除可能仍相容的其他 checkpoint，也不阻止重跑。

最終 merge、domain validation 與 completed transcript cache 成功後，chunk checkpoints 可保留供診斷／恢復，並由後續 cache retention policy 清理；本 change 不要求立即刪除。

### 5. 在 merge 階段統一處理全域時間與 overlap

每個 chunk adapter 仍輸出 local timestamps；merge 加上 chunk global start offset。Silence boundary 無 overlap 時直接按時間排序合併。Fallback overlap 使用雙重訊號：時間交集加 normalized text suffix/prefix match，選擇 deterministic 的最長可信重合區。

若去重信心不足，寧可保留疑似重複並發出 diagnostic，不可靜默丟失唯一文字。合併後重用既有 Transcript validation，確保 units 有序、非負、bounded；不在這一層生成 SRT cue，字幕 segmentation 保持下游單一實作。

### 6. Whole-job progress 以 committed duration 為主

已完成 checkpoint 的 chunk duration 是可恢復的 committed work；當前 chunk 可結合 adapter 的 whole-input estimated progress。總比例為 `(committed planned duration + current chunk estimated duration) / total planned duration`，標示 estimated，且 merge 與最終 cache 未成功前封頂 95%。Resume 時明確顯示載入的 completed chunk 數與 duration。

### 7. Auto device 不改變使用者選定的 model

Benchmark 可以比較 Nano 與 Paraformer並提出建議，但執行時不在使用者不知情下替換明確選擇的 model。`auto` 僅在該 model 的相容 long-form CPU/MPS profiles 間選 device；需要足量樣本、穩健 median RTF，且沒有超過 memory/swap/failure guardrails。

證據不足時使用保守 default 並標記原因。依目前短素材資料不能直接制定永久長內容 default，因此 implementation 先提供 evidence schema 與 deterministic fallback，再由完成的長素材評測更新設定。

### 8. Batch/VAD tuning 必須通過 gate

候選矩陣先以代表性 10–15 分鐘素材縮小範圍，再用至少一份 30–60 分鐘素材驗證；不要求每個候選都跑完整兩小時。採用條件包含相對基線 RTF 改善、peak RSS 上限、無持續 swap、無 failed chunks，以及 transcript/timestamp 差異在人工與自動門檻內。

不先加入跨 chunk parallelism：FunASR 已有內部 batching，且 Nano 峰值 RSS 約 6.6 GB；多 session 可能把 unified memory 推入 swap，使兩小時任務更慢且不穩定。

## Risks / Trade-offs

- **Chunk boundary 改變模型上下文並可能影響文字** → 優先靜音切點、保留 bounded overlap、加入單次完整推論對照與邊界 regression corpus。
- **Overlap 去重可能漏字或重複** → 時間與文字雙重匹配；低信心時保留文字並診斷，不靜默刪除。
- **Checkpoint schema 增加 cache 複雜度** → 版本化 manifest、checksum、原子寫入、逐 chunk validation，completed transcript cache contract 保持不變。
- **長素材 benchmark 成本高** → 先用 10–15 分鐘篩選，再以 30–60 分鐘驗證；兩小時案例只驗證最終候選與 resume。
- **Device profile 隨系統負載失真** → 使用近期多樣本穩健統計與 stability guardrails，不以單次最快值決策。
- **Sequential chunks 無法取得理論最大吞吐** → 優先可靠性與記憶體；只有量測證明資源餘裕後才另提有限並行 change。

## Migration Plan

1. 先加入 stage spans、long-form evaluation schema 與不改變行為的 benchmark runner。
2. 實作 deterministic planner、manifest/checkpoint domain 與純函式 merge，先以 fake adapters 驗證。
3. 導入 session lifecycle 與 sequential chunk workflow，保留 feature switch／threshold 讓短音訊繼續走原路徑。
4. 完成 Nano/Paraformer CPU/MPS 長素材矩陣後，才啟用 profile-aware auto device 與任何新 batch/VAD default。
5. 回滾時可停用 long-form chunking，舊 completed transcript cache 仍可讀；新 checkpoints 被忽略但不會破壞字幕生成。

## Open Questions

- 目標 Mac 的總 RAM 是多少，允許的 peak RSS 與 swap guardrail 應設為固定值還是可用記憶體比例？
- 長內容優先目標是最低總耗時、最低記憶體，還是「一小時內完成兩小時素材」？
- Device-specific checkpoints 是否能在實測證明 Nano／Paraformer CPU 與 MPS normalized output 等價後安全共享？
