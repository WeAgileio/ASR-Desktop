## Why

主要使用情境是處理兩小時以上的內容；在這個尺度下，模型載入只占極小比例，真正風險是長時間 ASR 吞吐、記憶體／swap、錯誤後從零重跑，以及缺少足夠數據選擇 Nano／Paraformer 與 CPU／MPS。需要一條可量測、可恢復且不犧牲 timestamp 與字幕品質的長音訊管線。

## What Changes

- 建立長音訊 benchmark contract，分離 model load、VAD、ASR、normalization 的耗時，並記錄 RTF、peak RSS、memory pressure／swap、model、device 與輸入語音特徵。
- 對 Nano／Paraformer、CPU／MPS 使用代表性長內容建立可比較 profile，讓 `auto` 在有相容證據時選擇穩定且較快的 model/device 路徑，而不是只依 MPS availability。
- 將兩小時以上音訊規劃為接近目標長度、優先落在靜音處的頂層 chunks，逐 chunk 辨識並以原子 checkpoint 保存。
- 在重跑時驗證 checkpoint identity，跳過已完成 chunks，從第一個未完成 chunk 恢復；不相容或損毀 checkpoint 必須安全忽略。
- 將 chunk-local timestamps 轉回全域時間軸，處理邊界 overlap／重複內容，輸出既有版本化 Transcript 與 SRT，不改變下游介面。
- 以 benchmark 結果調整 batching／VAD 參數；只有在 RTF 明顯改善、記憶體不惡化且 transcript/timestamp regression 通過時才採用。

## Capabilities

### New Capabilities

- `long-form-transcription`: 定義兩小時以上內容的效能量測、靜音感知分段、逐段 checkpoint、恢復、全域 timestamp 合併與品質／資源 guardrails。

### Modified Capabilities

- `local-video-transcription`: 將完成後才可重用的 transcript cache 擴充為仍保持原子與 identity 安全的逐 chunk checkpoint／resume 行為。

## Impact

- 影響 workflow orchestration、音訊切分／探測、ASR adapter lifecycle、cache schema、performance profile、device resolution、progress events、Transcript 合併與 evaluation tooling。
- 需要為 checkpoint 與 performance profile 增加版本化資料格式，但不得使舊 transcript cache 失效；舊 cache 仍可完整命中，新格式無法讀取時安全退化為完整重跑。
- 不改變支援的 CLI 模型名稱、最終 Transcript/SRT schema、繁體轉換、hotwords 語義或原始媒體；不承諾平行執行多個大型模型。
