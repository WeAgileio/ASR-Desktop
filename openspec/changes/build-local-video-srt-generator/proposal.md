## Why

需要一個能在 Apple Silicon Mac 上離線運作的個人字幕工具，將中文為主、英文為輔的影片直接轉為可用的繁體中文 SRT，避免上傳雲端、人工拆句與重複辨識。同時保留 Fun-ASR-Nano 與 Paraformer 的模型選擇，以因應中英混合準確度、長影片速度與 Mac 相容性的取捨。

## What Changes

- 新增本機影片轉 SRT 工作流，包含音訊擷取、語音辨識、字幕切分、繁體轉換與 SRT 輸出。
- 允許使用者明確選擇 `Fun-ASR-Nano-2512` 或 `paraformer-zh`，並使用共用的辨識結果格式與字幕生成管線。
- 支援中文為主、英文為輔的辨識、自訂熱詞及台灣繁體輸出。
- 在 Apple Silicon Mac 上自動選擇可用的運算裝置，並在 MPS 不可用或推論失敗時提供 CPU 退路。
- 保留含模型、版本、時間戳與辨識參數的中間結果，使字幕重新切分無需重跑 ASR。
- 第一版定位為字幕生成器，不包含內建字幕編輯器、字幕翻譯、影片燒錄、說話人分離或雲端功能。

## Capabilities

### New Capabilities

- `local-video-transcription`: 在 Mac 本機匯入影片、擷取音訊，並透過可選的 FunASR 模型產生標準化、可快取的辨識結果。
- `srt-generation`: 將字元或詞級時間戳轉換為易讀、不重疊的台灣繁體 SRT 字幕。

### Modified Capabilities

無。

## Impact

- 新增本機 Python 應用、命令列入口、FunASR 模型配接器、字幕切分器與檔案輸出。
- 新增 FunASR、PyTorch/torchaudio、FFmpeg、ModelScope 或 Hugging Face 模型下載與 OpenCC 相關依賴。
- 模型權重與中間辨識結果僅儲存於本機；不新增對外 API、雲端儲存或帳號系統。
- 需驗證 Fun-ASR-Nano 與 Paraformer 在 Apple Silicon MPS/CPU 上的輸出格式、速度、記憶體與時間戳品質。
