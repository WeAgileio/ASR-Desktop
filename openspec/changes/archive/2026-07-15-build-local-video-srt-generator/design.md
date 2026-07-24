## Context

專案目前沒有應用程式碼。此 change 建立一個供單一使用者在 Apple Silicon Mac 執行的離線字幕生成器，主要素材為中文且可夾雜英文。使用者需要在 Fun-ASR-Nano 的上下文與中英混合能力，以及 Paraformer 的成熟度、速度與較低資源需求之間自行選擇。

核心約束是全程本機運作、對長影片可恢復、不將特定模型的輸出格式滲透到字幕邏輯，並在 MPS 相容性不足時仍可以 CPU 完成。第一版提供 CLI，以先驗證字幕品質與 Mac 推論路徑；未來的本機圖形介面可共用相同 application service。

## Goals / Non-Goals

**Goals:**

- 將常見影片格式轉成格式正確、時間不重疊的 SRT。
- 支援使用者選擇 Fun-ASR-Nano-2512 或 paraformer-zh，並可指定熱詞。
- 以統一 transcript domain model 隔離 FunASR 輸出差異。
- 使用快取避免在只調整字幕分段或繁簡設定時重新辨識。
- 支援 Apple Silicon MPS 與 CPU 退路，並向使用者顯示處理階段與明確錯誤。

**Non-Goals:**

- 不建立字幕編輯器、影片播放器或時間軸 UI。
- 不進行字幕翻譯、字幕燒錄、說話人分離或即時串流辨識。
- 不提供雲端服務、對外 API、帳號、同步或多使用者功能。
- 不保證 Intel Mac、Windows 或 Linux 的安裝與加速體驗。

## Decisions

### 1. 以 CLI 為第一版介面

提供單檔轉換命令，參數包含輸入影片、模型、熱詞、運算裝置、輸出路徑與字幕切分設定。CLI 將呼叫獨立的 application service，不直接承擔 ASR 或 SRT 邏輯。

替代方案是立即建立本機 Web UI。由於目前是個人工具且模型與時間戳品質尚需實測，CLI 的实作與測試成本較低，也更適合未來批次自動化。

### 2. 模型使用 adapter 並輸出統一 Transcript

建立 `FunAsrNanoAdapter` 與 `ParaformerAdapter`，兩者將原始輸出轉成統一資料結構：完整文字、影片時長、語言、帶起訖毫秒的 token/word 列表，以及模型名稱、revision、device、熱詞與處理時間 metadata。所有時間在 domain model 中使用非負整數毫秒。

替代方案是讓字幕切分器分別理解兩種模型輸出。這會使字幕規則、快取與測試與模型緊密耦合，不採用。

### 3. 使用 FFmpeg 先標準化音訊

以 FFmpeg 將影片音訊轉為單聲道 16 kHz PCM/WAV 中間檔，並使用 ffprobe 獲取時長。程序以參數陣列執行 subprocess，不將使用者輸入插入 shell command。

替代方案是直接將各種影片傳給 FunASR。預先標準化可降低容器格式差異，並使快取、長度驗證與失敗診斷更可控。

### 4. 模型與 device 分開選擇

模型預設為 `fun-asr-nano`，使用者可改選 `paraformer`。Device 預設為 `auto`：當 MPS 可用時先執行小型預檢，預檢或實際推論出現已辨識的 MPS 相容性錯誤時，以 CPU 重新載入模型並重試一次。使用者明確指定 `mps` 時不靜默變更 device；指定 `cpu` 時不嘗試 MPS。

不採用「auto 自動選模型」，因為模型變更會影響文字與時間軸，應由使用者明確決定並可重現。

### 5. 分離 ASR 快取與字幕產物

中間 transcript 以 versioned JSON 儲存。快取身分由輸入檔內容指紋、模型 ID/revision、語言、熱詞、音訊前處理版本與會影響辨識的參數決定。字幕最大字數、持續時間與繁簡轉換不影響 ASR 快取。JSON 採原子替換，防止中斷時留下被當成成功結果的半成品。

### 6. 字幕切分使用確定性規則

切分器先依句末標點，再依逗號、停頓、最大字數與最長持續時間建立 cue；過短 cue 依時間與長度限制合併。中文字元與英文單字採不同的切斷單位，英文單字內不切斷。最後強制 cue 時間單調、非負、不重疊且不超過媒體時長。

預設值為每 cue 最多 22 個顯示單位、最長 6 秒、目標最短 1 秒。這些參數可調整，但相同 transcript 與設定必須產生相同 SRT。

### 7. 繁體轉換發生在切分後

原始 transcript 保留模型輸出；SRT cue 在切分後透過 OpenCC 台灣繁體設定轉換。這避免轉換改變 token 對齊，也讓未來可以從同一 transcript 產生不同中文字形。

### 8. 產物與日誌不覆寫輸入

預設 SRT 寫入影片旁並使用同名 `.srt`。存在同名檔時需要明確 `--overwrite` 才可替換。輸入媒體永不修改。中間音訊與下載模型置於應用快取目錄，不預設放在影片旁。

## Risks / Trade-offs

- [Fun-ASR-Nano 在 MPS 上可能有不支援的算子或記憶體問題] → 使用 device 預檢、可觀測的 CPU 退路與兩種模型的真實 Mac 測試素材。
- [800M Nano 模型處理長影片可能過慢或造成 swap] → 將 Paraformer 保留為輕量選項，記錄媒體時長、處理時間、device 與峰值資源觀測結果。
- [兩種模型的時間戳粒度或輸出欄位隨版本變化] → Adapter 對原始結果進行 schema validation，快取記錄 model revision 與 transcript schema version。
- [規則切句在所有說話速度與影片類型上不會同時最佳] → 提供少量可調參數，保留 transcript 以便快速重生 SRT，並使用代表性測試集調校預設值。
- [模型首次下載大且可能中斷] → 在開始前顯示模型 ID 與下載階段，使用模型 hub 快取與可重試的下載機制。
- [OpenCC 詞彙轉換可能不符合個別上下文] → 保留原始 transcript，並讓繁體轉換為可選輸出設定。
- [FFmpeg 未安裝或版本不適用] → 啟動前驗證 `ffmpeg`/`ffprobe` 可執行與版本，失敗時提供明確安裝提示。

## Migration Plan

這是新應用，無現有使用者資料或 API 要遷移。實作依次建立 domain model、媒體前處理、模型 adapters、快取、字幕引擎與 CLI，再用短音訊與代表影片驗證。若 Nano 的 Mac 路徑未達可用標準，仍保留其 adapter 但將 CLI 預設暫時改為 Paraformer，不影響 transcript 或 SRT 管線。

## Open Questions

- 目標 Mac 的晶片世代與記憶體容量，以及 Nano 在該機器上可接受的 real-time factor 門檻為何？
- Fun-ASR-Nano 的 Python MPS 路徑與 llama.cpp/GGUF 路徑，何者能在 Mac 上同時提供最佳速度與完整字元時間戳？
- 預設的台灣繁體 OpenCC profile 是否需要另加使用者專有詞替換表？

