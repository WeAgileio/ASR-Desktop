## Why

目前轉錄需手動執行本機 CLI，無法透過網頁提交 Google Drive 資料夾、追蹤批次進度並取得回傳結果。需要在同一台 M4／16GB Mac mini 上建立非同步服務，同時保留原生 MPS 加速與既有長音訊續跑能力。

## What Changes

- Docker Compose 部署 Web／FastAPI、SQLite 持久化儲存、Redis／RQ 佇列及受限的 RQ Dashboard。
- macOS 原生 RQ SpawnWorker 一次處理一個完整檔案任務：下載、辨識、輸出、上傳；由 launchd 管理。
- 原生掃描程序使用服務帳號或使用者 OAuth 遞迴掃描 Drive，建立可去重的批次與檔案任務；來源與目的地獨立設定。
- 提供繁體 TXT、SRT 與完成資訊，保存對應 Drive 結果連結，重試不重複交付。
- 新增任務狀態、心跳、入列補送、恢復、暫停領取及手動重試；保留現有 CLI 行為。

## Capabilities

### New Capabilities

- `drive-transcription-intake`: Drive 來源與目的地檢查、遞迴掃描、版本識別及批次建立。
- `rq-transcription-execution`: RQ 單工執行、可靠派送、狀態回報與失敗恢復。
- `drive-transcription-delivery`: 本機結果產生、Drive 冪等上傳與交付確認。
- `transcription-service-management`: Web 操作、SQLite 紀錄、同機部署、監控及程序管理。

### Modified Capabilities

無。此變更新增服務層，沿用本機轉錄、字幕及進度規格，不改變既有 CLI 契約。

## Impact

- 於既有 `src/asr_srt/workflow.py`、進度事件與快取介面外新增服務、worker、Drive 整合與 TXT 匯出層；不在容器內執行模型。
- 新增 FastAPI、ASGI server、RQ、Redis client、Google 驗證／Drive client 等可選依賴，固定驗證版本；Web 映像避免安裝 PyTorch／FunASR。
- 新增 Docker Compose、launchd 設定範本、資料遷移與操作文件；Redis 和 SQLite 使用本機持久化 volume，金鑰僅在 Mac。
- 已測試來源可列出多層目錄，但根目錄不可新增子項目，且未回傳 shared-drive ID。真實寫入驗收需使用可寫入的共用雲端硬碟目的地，或完成使用者 OAuth 授權後使用 My Drive 目的地；不將真實來源 ID 或私鑰放進設定範本。
