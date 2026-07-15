## Context

現有進度系統只把具有穩定 whole-input scope 的 adapter callback 視為 actual。FunASR 的 `AutoModel.generate()` 在啟用 VAD 時，先取得整份輸入的 VAD 區段，依區段長度排序並動態組 batch；內層 `inference()` 的 `progress_callback(current, total)` 只描述當次呼叫，會在下一個 batch 重置。Nano 與 Paraformer 因此都宣告 `progress_scope = "batch"`，workflow 正確地忽略這些數字。

VAD 結果包含每個語音區段的開始與結束時間，所以在 ASR batch 排程開始前已能建立穩定的全域語音工作量。這個訊號比切片個數更能反映工作量，但區段內容、padding、batching 與硬體仍會使耗時不完全線性，因此只能作為 estimated progress。

## Goals / Non-Goals

**Goals:**

- 在不改變 VAD 與 batching 決策的情況下，觀測全域 VAD 區段及其完成狀態。
- 以已完成區段的語音時長除以全部 VAD 語音時長，產生單調、bounded 的 estimated transcription progress。
- 保持 adapter contract 能區分 batch-local、whole-input estimated work 與 whole-input actual measurements。
- 當 runtime 不相容、觀測資料不一致或 CPU/MPS fallback 重啟時安全退化，不影響辨識結果。

**Non-Goals:**

- 不把切片數、語音時長或 batch-local callback 宣稱為 actual ASR completion。
- 不改變 FunASR 的 VAD 參數、區段排序、動態 batching、模型推論或結果合併邏輯。
- 不以實體暫存音訊檔切片，也不提供可恢復的逐片 transcription。
- 不計算跨階段的單一 job 百分比。

## Decisions

### 1. 新增 whole-input estimated-work 進度語義

adapter progress measurement 將能表達 `scope = whole-input` 與 `kind = estimated`，並以毫秒語音工作量作為 current/total。workflow 只把同時具有穩定 total、合法範圍及單調 current 的 measurement 轉成 transcription estimated event；既有 `global + actual` contract 保留給未來真正可靠的 adapter。

選擇時長權重而非切片個數，因為 2 秒與 30 秒區段不應各占相同百分比。沒有使用 batch 數，因為 FunASR 的 batch 由區段長度、裝置及 threshold 動態形成，不能在開始時視為穩定工作單位。

### 2. 以受版本保護的 FunASR observation bridge 取得訊號

adapter 建立模型後安裝局部、可撤銷的 observation bridge。bridge 僅觀察單次 `generate()` 內的 VAD 結果與主 ASR inference 完成邊界：

1. VAD 回傳後擷取所有合法 `[start_ms, end_ms]`，建立依 FunASR 相同排序規則排列的區段工作量 ledger。
2. 每次主 ASR inference 成功回傳後，依該次結果數量結算 ledger 中相對應的區段時長。
3. 發送累積完成毫秒數與固定總毫秒數，不轉送內層會重置的 callback。
4. `generate()` 結束或失敗時無條件移除 bridge，避免污染模型或後續呼叫。

bridge 必須是 pass-through：不得改寫參數、回傳值、區段內容或排程。它只在已驗證的 FunASR runtime identity 與預期呼叫形狀下啟用；任何結構不符都停用 segment estimate 並記錄可診斷原因。相較複製整個 `inference_with_vad()`，此方式減少與上游程式分叉；相較直接累加 callback total，它能先取得穩定的 whole-input denominator。

若 FunASR 未來提供正式的全域 VAD/segment callback，adapter 應優先使用公開 API，並移除對該版本的 observation bridge。

### 3. 成功前封頂並與歷史 RTF estimate 協調

segment-derived current 在 running 狀態封頂於 total 的 95%；只有 workflow 收到有效 Transcript 後才發出 completed。這避免最後一個 ASR batch 結束後，結果正規化、標點處理或合併尚未成功時先顯示 100%。

有 segment measurement 時，它成為 transcription 百分比的主要來源；歷史 RTF 仍可提供 ETA，但不得用 wall-clock current 覆蓋或使百分比倒退。沒有 segment measurement 時完全沿用既有歷史 RTF estimate；兩者皆不可用時維持 indeterminate。

### 4. fallback/retry 建立新的 measurement epoch

MPS 失敗並改用 CPU 時，先終止原 epoch，再為 CPU retry 建立新的 segment ledger。renderer 可保持同一 transcription phase，但 workflow 不得將 MPS 的已完成工作量加到 CPU total，亦不得讓先前較高的百分比冒充 CPU 的實際狀態。事件訊息需清楚指出重新開始估算。

### 5. 嚴格驗證後才呈現

以下任一情況會停用當次 segment estimate：總語音時長為零、負值或非有限值；完成區段數超過 ledger；ASR 結果數與預期 batch 不符；current 倒退或超過 total；多輸入形狀無法可靠對應。退化只影響進度呈現，不得中止 transcription。

## Risks / Trade-offs

- **FunASR 私有呼叫拓撲在升級後改變** → 以 runtime/version guard、形狀驗證與 pass-through fallback 隔離，並加入支援版本的契約測試。
- **語音時長不等於推論耗時** → 永遠標示 `estimated`，保留歷史 RTF 作 ETA，且不承諾線性準確度。
- **短片段 batching 與 padding 使時長權重偏差** → 接受為粗略估算；測試只要求 bounded、單調與全域語義，不要求 wall-clock 精準度。
- **observer 包裝可能遺漏清理** → 使用 context-managed 安裝與 `finally` 復原，並測試成功、例外及 fallback 路徑。
- **MPS retry 造成畫面百分比重置** → 明確顯示 retry epoch；正確性優先於視覺上的單調連續。

## Migration Plan

1. 先擴充 adapter measurement contract 與 workflow 驗證，保持既有 adapters 的預設行為不變。
2. 加入 FunASR observation bridge 與隔離測試，再分別為 Nano、Paraformer 啟用 capability。
3. 以安裝版本的真實模型 smoke test 驗證 transcript、timestamps 與 cache identity 在進度開關前後一致。
4. 若線上或 smoke test 發現 runtime 不相容，可停用 adapter capability；workflow 會自動回到 RTF estimate 或 indeterminate，無資料遷移需求。

## Open Questions

- 目前支援的 FunASR 版本範圍應採精確 allowlist，還是以結構 capability probe 為主、版本僅用於診斷？
- plain/rich renderer 是否需要額外顯示「依語音區段估算」，或沿用現有 `estimated` 標記已足夠？
