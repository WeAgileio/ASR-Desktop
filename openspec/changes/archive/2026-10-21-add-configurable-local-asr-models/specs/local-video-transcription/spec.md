# Spec Delta

## MODIFIED Requirements

### Requirement: Select a supported ASR model
系統 SHALL 允許使用者選擇登錄配置中支援的模型，包括 `fun-asr-nano`、`paraformer`、Taiwan Tongues ASR CE 與 Breeze ASR 25，並於結果 metadata 記錄選用模型與固定版本。

#### Scenario: Fun-ASR-Nano is selected
- **WHEN** 使用者選擇 `fun-asr-nano`
- **THEN** 系統使用既有 Fun-ASR-Nano-2512 Adapter，將文字與時間戳轉為共用 transcript

#### Scenario: Paraformer is selected
- **WHEN** 使用者選擇 `paraformer`
- **THEN** 系統使用既有 paraformer-zh、VAD 與標點流程，輸出共用 transcript

#### Scenario: Additional local model is selected
- **WHEN** 使用者選擇已登錄且準備完成的 Taiwan Tongues ASR CE 或 Breeze ASR 25
- **THEN** 系統在本機 CPU 執行對應引擎，並將文字與真實時間戳轉為共用 transcript

#### Scenario: Unsupported model is selected
- **WHEN** 使用者提供未登錄的模型識別碼
- **THEN** 系統在下載或載入模型前拒絕工作，並列出支援的識別碼

### Requirement: Apply user-provided hotwords
系統 SHALL 接受有序且非空的熱詞集合，依選定模型支援的參數格式傳入推論，並將正規化熱詞納入快取識別。模型未支援熱詞時 SHALL 在接受工作前明確拒絕非空熱詞，不得靜默忽略。

#### Scenario: Hotwords are supplied
- **WHEN** 使用者為支援熱詞的模型提供有效熱詞
- **THEN** 系統在辨識時使用並記錄熱詞

#### Scenario: No hotwords are supplied
- **WHEN** 使用者未提供熱詞
- **THEN** 系統不加入合成熱詞

#### Scenario: Model does not support hotwords
- **WHEN** 使用者為不支援熱詞的模型指定非空熱詞
- **THEN** 系統在接受工作前回報該模型不支援熱詞

## ADDED Requirements

### Requirement: Validate model device capabilities
系統 SHALL 在接受工作前依選定模型的裝置能力驗證設定。第一階段兩個新增模型 SHALL 支援 CPU，`auto` SHALL 選擇 CPU；明確指定不支援的 GPU 或 MPS SHALL 被拒絕。既有模型的裝置政策 SHALL 維持原有行為。

#### Scenario: Additional model uses automatic device selection
- **WHEN** 使用者為任一新增模型選擇 `auto`
- **THEN** 系統選擇 CPU 並記錄實際執行裝置

#### Scenario: Additional model is explicitly assigned an unsupported device
- **WHEN** 使用者為僅支援 CPU 的模型選擇 GPU 或 MPS
- **THEN** 系統在接受工作前說明該模型支援的裝置
