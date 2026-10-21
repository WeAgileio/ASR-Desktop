# local-asr-model-registry Specification

## Purpose

讓使用者透過一致的模型清單選用不同引擎的本機語音辨識模型，並在準備模型前了解電腦需求；模型完成下載與校驗後，能在無網路的環境產生文字與字幕，且保留可重現的模型版本資訊。

## Requirements

### Requirement: Configure local model registrations
系統 SHALL 從版本化配置取得模型識別碼、顯示名稱、引擎、完整資產、裝置及功能能力，且 GUI 與 CLI SHALL 使用一致的清單。相容既有引擎的新模型 SHALL 可透過配置登錄而無須新增模型名稱分支；未支援的引擎 SHALL 明確被拒絕。

#### Scenario: Compatible model is registered
- **WHEN** 配置加入完整且有效的相容引擎模型
- **THEN** 模型清單與工作驗證提供該模型，且使用配置指定的引擎

#### Scenario: Unsupported engine is configured
- **WHEN** 模型配置指定未支援的引擎
- **THEN** 系統回報配置錯誤且不開始推論

### Requirement: Transcribe with the additional local models
系統 SHALL 提供 Taiwan Tongues ASR CE 與 Breeze ASR 25 的本機 CPU 轉錄，保留既有模型，並將辨識結果及真實時間戳轉為共用 transcript 與既有字幕輸出。第一階段 SHALL 不要求 GPU 加速或特定執行速度。

#### Scenario: Prepared model runs offline
- **WHEN** 使用者選擇已準備完成的任一新增模型並以 CPU 轉錄有效錄音
- **THEN** 系統在無外連下載、安裝依賴或上傳音訊的情況下產生文字與 SRT，並記錄模型及固定版本

#### Scenario: Model assets are incomplete
- **WHEN** 模型缺少任何必要資產或校驗失敗
- **THEN** 模型不可用，且系統提示下載或修復而不在推論時補下載

### Requirement: Explain computer requirements on the model page
模型頁 SHALL 顯示各模型支援平台、CPU 與 GPU 可用性、記憶體建議、下載量及準備所需可用磁碟空間。未實測的記憶體數值 SHALL 標示為估算建議，不得宣稱為已驗證最低需求；沒有可靠最低需求時 SHALL 明確說明。

#### Scenario: User reviews a model before downloading
- **WHEN** 使用者開啟模型頁
- **THEN** 不需先下載即可閱讀電腦需求、數值依據與限制，實際資產總大小與動態準備空間獨立呈現

### Requirement: Preserve immutable execution identity
已接受的工作 SHALL 固定模型資產及推論配置；變更引擎或影響辨識的設定 SHALL 使不相容快取失效，且不得將舊工作靜默切換到新版配置。

#### Scenario: Registry changes after submission
- **WHEN** 工作排隊後模型配置更新
- **THEN** 該工作仍使用接受時固定的資產與推論設定
