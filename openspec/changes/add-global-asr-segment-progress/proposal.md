## Why

FunASR 在整合 VAD 與動態 batching 時只暴露會重置的 batch-local callback，因此長時間 transcription 首次執行仍只能顯示 indeterminate 狀態。VAD 完成後其實已有完整語音區段清單；若能取得全域區段工作量，就能提供更有資訊量、但仍誠實標示為估算的 ASR 進度。

## What Changes

- 擴充 ASR adapter 的進度語義，讓支援的 FunASR 整合可回報整份輸入的穩定語音工作量總數與單調遞增的已完成工作量。
- 以已完成 VAD 語音區段的時長權重，而非單純切片個數或 batch-local callback，計算 transcription estimated progress。
- 在 VAD 尚未產生穩定全域總量、adapter 不支援此訊號或訊號失效時，維持既有歷史 RTF estimate 或 indeterminate fallback。
- 保留 estimated 與 actual 的界線：segment-derived 進度必須標示為 estimated，且成功完成前不得到達 100%。
- 加入全域範圍、單調性、動態 batching、CPU/MPS fallback 與退化路徑的測試覆蓋。

## Capabilities

### New Capabilities

- `asr-segment-progress`: 定義從全域 VAD 語音區段工作量產生 transcription estimated progress、驗證其範圍，以及無可靠訊號時的 fallback 行為。

### Modified Capabilities

<!-- No canonical specs currently exist under openspec/specs; this change composes with the pending job-progress-reporting capability without redefining it. -->

## Impact

- 影響 `ASRAdapter`／`AdapterRequest` 的進度 contract、FunASR Nano 與 Paraformer adapters、workflow 的 transcription progress producer，以及相關 renderer/event 測試。
- 可能需要在不改變辨識結果與排程策略的前提下，為 FunASR VAD pipeline 提供受控的觀測整合點；不得依賴不穩定的 batch-local current/total 作為全域百分比。
- 不改變 CLI 參數、模型選擇、VAD 切片設定、batching 決策、transcript cache identity、字幕內容或輸出格式。
