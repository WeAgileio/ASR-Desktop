# Proposal

## Why

目前本機轉錄需要手動準備 Python、FFmpeg 與模型，既有視覺化管理頁則依賴另一套 Drive／Docker 服務，無法提供直接安裝的 Mac 桌面批次工具。需要讓 Apple Silicon 使用者透過獨立視窗或 CLI 管理同一批錄製好的音訊／影片，取得逐字稿與字幕，並以實測證據決定 CPU／GPU 的使用方式。

## What Changes

- 提供 Apple Silicon 專用桌面 App，內建執行環境與媒體工具；模型在安裝後由 App 或 CLI 下載，完整下載後可離線轉錄。
- GUI 與 CLI 共用本機任務、設定、模型與歷史紀錄，支援多檔／資料夾提交、逐檔排隊、進度、暫停領取、取消、重試及長音訊恢復；關閉視窗不終止背景工作。
- 每個成功任務預設產生台灣繁體 TXT 與 SRT，可選擇結構化 JSON；保護來源與既有輸出，個別失敗不阻塞其餘檔案。
- 提供模型下載進度、續傳、完整性校驗及固定版本管理，不在轉錄期間隱式補下載依賴。
- 提供「自動／CPU／GPU」；GPU 對應 MPS。自動模式依相容且足量的效能／資源證據選擇，資料不足時以 CPU 為保守預設，已知 MPS 相容性失敗時明確退回 CPU。
- 保留既有 `asr-srt` 單檔 CLI 與 `cpu`／`mps` 參數；共用核心的 `auto` 預設策略會從優先可用 MPS 改為依證據選擇，須在文件說明此行為變更。
- 開發建置採明確標示的直接 helper 啟動模式，讓功能開發不依賴正式簽署；正式建置仍使用 SMAppService，簽署與受管理服務生命週期驗收保留於發行階段。

第一版不包含麥克風即時辨識、語音輸入法、字幕編輯器、雲端轉錄、Intel Mac 或其他作業系統。

## Capabilities

### New Capabilities

- `macos-desktop-transcription`: 可直接安裝的 Apple Silicon App、首次使用、桌面任務操作、背景執行與環境診斷。
- `local-transcription-jobs`: 本機批次來源檢查、持久化佇列、單工執行、控制與恢復、逐字稿／字幕交付。
- `transcription-command-interface`: 與桌面等價的 CLI、穩定的機器可讀結果、跨入口狀態同步及背景服務生命週期。
- `local-model-management`: 安裝後下載模型與完整相依資產、驗證、離線就緒、固定版本與安全移除。

### Modified Capabilities

- `local-video-transcription`: 將裝置選擇改為有證據的自動策略，明確定義 CPU 預設、MPS 失敗處理及效能證據有效性。
- `long-form-transcription`: 長音訊裝置選擇採相同的證據資格與資源門檻，不以短樣本推定長錄音效能。

## Impact

- 新增 SwiftUI 桌面工程、arm64 App／DMG 打包、內建 CLI、本機協調程序與持久化任務資料；推論沿用 `src/asr_srt/`，不依賴 Redis、Docker 或 Google Drive。
- 擴充模型解析、不可變模型版本識別、受控取消、裝置決策及效能採樣介面；TXT 匯出抽成可重用核心能力，維持既有 Drive 服務相容。
- 新增 GUI／CLI 共用的版本化本機通訊契約；固定並驗證 Python、FunASR、PyTorch／torchaudio 與 FFmpeg 的 arm64 發行依賴。
- 增加模型下載、跨入口任務控制、意外中斷恢復、離線轉錄及乾淨 Mac 安裝驗收；目前既有短音檔紀錄不視為桌面打包或長音訊驗收通過。
- 既有 `add-drive-rq-transcription-service` 變更維持獨立；本提案不授權 Git 提交、tag、push 或發布 Release。
