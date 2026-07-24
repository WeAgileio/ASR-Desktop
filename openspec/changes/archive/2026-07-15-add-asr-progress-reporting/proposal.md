## Why

音訊擷取、模型載入與 ASR 在長影片上可持續數分鐘以上，現有 CLI 只在階段切換時輸出一行訊息，使用者難以分辨「正常處理」與「程式卡住」。需要一組誠實、可觀測的進度回報：能精準量測時顯示百分比，無法量測時顯示運行時間與明確標示的估算。

## What Changes

- 將現有只含 `phase`/`message` 的進度事件擴充為結構化 lifecycle event，支援 pending、running、completed、skipped 與 failed 狀態。
- 為 FFmpeg 音訊擷取回報基於媒體時間的真實百分比。
- 為模型載入與無可靠全域 callback 的 ASR 顯示 spinner、已經時間與定期 heartbeat，不偽造精準百分比。
- 當 adapter 能提供具有明確全域 scope 的 `current/total` 時，顯示真實 ASR 百分比；否則使用過去同模型/裝置完成任務的 RTF 提供明確標示為「預估」的 ETA。
- 在互動 TTY 中使用單一可更新的多階段進度視圖；在 pipe、CI 或 log 環境中退回不含 ANSI 控制碼的逐行事件。
- 停用或整合 FunASR 原生 `tqdm` 輸出，避免與應用的進度顯示互相覆寫。
- 快取命中時明確將音訊擷取與 ASR 標示為 skipped，而不是顯示假的瞬間 100%。
- 不在此 change 中重寫 FunASR 的 VAD/batching 編排，也不為了百分比而改變辨識分段與模型輸出。

## Capabilities

### New Capabilities

- `job-progress-reporting`: 定義本機影片轉 SRT 任務的結構化階段進度、真實/預估值語義、TTY 呈現與純文字 log 行為。

### Modified Capabilities

無。

## Impact

- 擴充 `ProgressEvent`、`LocalTranscriptionService`、媒體處理層、ASR adapter contract 與 CLI renderer。
- 新增可持久化的 model/device RTF 效能輪廓，但不納入 transcript cache identity，也不影響辨識結果重現性。
- 新增 Rich 為直接 CLI 依賴，並保留無色、可重定向的 plain renderer。
- 依賴 `build-local-video-srt-generator` 建立的 workflow、model adapters 與 CLI；此 change 不解決尚未完成的 Paraformer 權重實機測試。
