# Preparing local models

## Taiwan Tongues 與 Breeze ASR 25

模型清單包含 `taiwan-tongues` 與 `breeze-asr-25`，各約下載 3.09 GB。
兩者第一版提供本機 CPU 推論，`auto` 使用 CPU；不提供 GPU／MPS 或熱詞設定。
Taiwan Tongues 使用官方 CTranslate2 模型，Breeze 使用官方 Transformers Whisper 模型，
不需要另外啟動上游 API 服務。準備完成後不外連；缺少檔案時請明確下載／修復。

在模型頁可以看到平台、CPU、GPU、記憶體建議及實際下載與磁碟準備空間。
Taiwan Tongues 的 32 GB RAM 是官方 CPU 建議；Breeze 的 16 GB RAM 是工程估算。
這些都不是經過驗證的最低需求，也不作為禁止執行的門檻。
CPU 可能較慢。兩個引擎啟用逐字／詞時間戳，供現有字幕長度與時長設定使用；
中文分詞粒度與既有模型可能不同，不將估算的平均字時長冒充模型對齊結果。
辨識語言預設「中文」對應 `zh`，英文可填 `en`，自動偵測可填 `auto`；
Breeze 主要針對華語與中英混用，不能因為採用 Whisper 就視為已驗證所有語言。

### 配置與固定工作版本

共用清單為 `src/asr_desktop/data/models.json`。模型的 `execution` 包含
`engine`、`primary`、`devices`、`hotwords`、`required_files` 與 `parameters`。
引擎為明確允許的 `funasr-nano`、`funasr-paraformer`、`faster-whisper`、
`transformers-whisper`，不允許任意 Python import。新增相容引擎的權重時，
填入完整模型資產及能力資料即可；新引擎仍需新增 Adapter 並納入 runtime。
`display_name` 與 `requirements` 用於模型頁。

新模型使用 `snapshot_schema: 2`，快照 SHA-256 計算內容為排序且緊湊 JSON 的
`{"components": component_definitions, "execution": execution}`，包括所有辨識設定。
舊快照仍採原本的元件識別方式，不改動既有工作。接受工作時保存整份定義，
更新清單不會改動已排隊工作的權重或參數，快照識別也用於 transcript/checkpoint 快取。

維護者可執行 `python3 desktop/scripts/add_whisper_catalog.py` 更新兩個官方模型，
生成固定 commit、檔案大小與 SHA-256；一般使用者不需執行這個腳本。
`update_model_catalog.py` 更新 FunASR 時會保留其他引擎模型。
原始 CLI `asr-srt --model ...` 共用已準備的 desktop 模型庫；先從模型頁或 desktop CLI 下載模型。

### 維護者驗收

`prepare_whisper_models.py` 只在明確執行時下載到專案內的獨立驗收模型庫；
`smoke_whisper_models.py` 使用該模型庫並封鎖推論程序的 Python 外連。
先將一段測試錄音轉為 mono 16 kHz PCM WAV，再執行：

```sh
PYTHONPATH=src build/desktop/packaging-env/bin/python desktop/scripts/prepare_whisper_models.py
PYTHONPATH=src build/desktop/packaging-env/bin/python desktop/scripts/smoke_whisper_models.py --audio /absolute/path/sample.wav
PYTHONPATH=src build/desktop/packaging-env/bin/python desktop/scripts/smoke_whisper_models.py --audio /absolute/path/sample.wav --helper "/absolute/path/ASR Desktop.app/Contents/MacOS/ASRDesktopHelper"
```

原生批次整合測試為 `verify_whisper_batch.py --app /absolute/path/App`，
使用驗收模型庫中的 `sample.wav`，串接 CLI、背景服務、真實 worker 與三種輸出。
若另有測試服務正在使用此驗收資料庫，須先停止該測試服務。
驗收輸出保留於 `build/desktop/local-whisper/`，不作為最低硬體或辨識品質保證。

Install the complete App, then choose **模型 → 下載／修復**, or use the bundled command:

```sh
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models list --json
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models download fun-asr-nano --json
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models list --json
```

Preparation is asynchronous. Inspect `state`, `downloaded_bytes`, `total_bytes`, and `ready`. Only `ready=true` permits new inference. Download and transcription have separate progress. Both clients use the same store in `~/Library/Application Support/ASR Desktop/models`. About 2.15 GB transfers for Nano and 1.30 GB for Paraformer; the returned `required_free_bytes` includes workspace headroom. Installation itself contains no model weights.

Retry the same download command after a network interruption or capacity failure. Completed, hash-verified files remain reusable. Eligible partial files preserve a strong ETag and immutable catalog identity; the next transfer sends Range and If-Range. A changed identity or unsupported range discards only that asset's partial transfer. All assets must match catalog size and SHA-256 before publication. No Python installation scripts run during preparation.

```sh
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models verify paraformer --json
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models remove paraformer --json
```

Verification rehashes every required asset and reports damaged/missing models as unavailable. Repair is an explicit download action; inference never fetches missing data. Removal reports `model_in_use` and job IDs if queued/running/interrupted work still references the snapshot. Cancel those jobs first if they are no longer needed. Completed or cancelled history and exported results survive model removal. A later retry may require downloading the original snapshot.

The App's catalog pins main weights, VAD, punctuation, tokenizer and configuration to immutable commits. New App catalogs do not alter previously accepted jobs or saved definitions. Prepared inference uses absolute local paths and blocks Python outbound sockets. Existing developer hub caches are not the desktop model store. Offline packaging smoke is evidence for the current development environment; full OS-level offline and clean-Mac acceptance remain separate release gates.

Maintainers can reproduce real interrupted-HTTP resume using `PYTHONPATH=src build/desktop/packaging-env/bin/python -m unittest tests.desktop.test_download_http -v`. The fixture transfers 7,000 bytes then closes early; retry must send the validated offset and produce the original full checksum. It uses a local HTTP server and disposable model store, not a model registry simulation or user data. Protocol, failure and publication tests are in `tests/desktop/test_models.py`.
