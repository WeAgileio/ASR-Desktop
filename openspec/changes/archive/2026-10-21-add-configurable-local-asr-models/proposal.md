# Proposal

## Why

使用者希望在 Mac 本機選用 Taiwan Tongues ASR CE 與 Breeze ASR 25，並讓相同推論引擎的新模型能透過配置登錄。現有清單僅配置下載資產，模型驗證、載入與介面仍固定為兩個 FunASR 模型。

## What Changes

- 建立共用模型登錄，集中引擎、資產、裝置與功能能力設定，保留既有模型。
- 支援 Taiwan Tongues 的 faster-whisper 與 Breeze 的 Transformers Whisper 本機 CPU 推論，下載完成後離線產生文字及字幕。
- 模型頁依配置顯示平台、CPU、記憶體建議、下載量與準備所需空間；估算與實測資訊分開標示。
- GUI 與 CLI 使用同一份模型清單、驗證與固定版本資產。
- 不納入遠端推論、自訂模型編輯介面、GPU 加速保證或效能門檻。

## Capabilities

### New Capabilities

- `local-asr-model-registry`: 配置驅動的本機模型登錄、引擎能力及電腦需求展示，涵蓋兩種新增模型的離線執行。

### Modified Capabilities

- `local-video-transcription`: 將模型選擇擴充為登錄清單，依模型能力驗證裝置與熱詞。

## Impact

影響 Python 模型管理、Adapter、工作設定及快取識別，SwiftUI 模型與設定頁、CLI 說明，以及 runtime 相依套件與打包。沿用現有下載校驗、任務固定快照、離線邊界與字幕輸出；既有 local-model-management 變更尚未歸檔，新增設計必須維持其完整資產與固定版本規則。
