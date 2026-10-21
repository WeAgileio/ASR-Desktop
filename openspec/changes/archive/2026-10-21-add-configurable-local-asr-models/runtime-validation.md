# Runtime Validation

## Environment

- 驗收日期：2026-10-21（Asia/Taipei）。
- 本機 macOS 26.5.2、arm64、10 個邏輯核心；Python 3.11.15。
- PyTorch 2.8.0、Transformers 4.57.6、faster-whisper 1.2.1、CTranslate2 4.8.3、PyAV 18.1.0、ONNX Runtime 1.31.0。
- 隔離資料目錄：`build/desktop/local-whisper/`；不使用使用者的正式 workspace。
- 測例：以 macOS Meijia 本機合成的 6.836 秒中文錄音，轉為 mono 16 kHz PCM WAV。不是使用者錄音，也不是語料品質評測。

## Source CPU Smoke

兩個模型從官方固定版本下載，所有必要檔案依 catalog 的大小與 SHA-256 完整校驗，並再次執行 verify。

| 模型 | 官方 revision | 必要資產總大小 |
| --- | --- | --- |
| Taiwan Tongues | `46b5eb7ee167ac2fd06cfe02f40e8fac416e5086` | 3,090,476,757 bytes |
| Breeze ASR 25 | `cffe7ccb404d025296a00758d0a33468bec3a9d0` | 3,092,421,455 bytes |

執行 `PYTHONPATH=src build/desktop/packaging-env/bin/python desktop/scripts/smoke_whisper_models.py` 通過。
兩個獨立推論程序於載入前設定 HF／Transformers offline，並封鎖 Python socket.connect、connect_ex 與 create_connection；沒有推論時下載。這是 Python 層的封鎖，未宣稱為作業系統防火牆驗收。

- Taiwan Tongues：辨識出「大家好這是本期語音辨識測試今天我們要確認字幕可以正常產生」，啟用逐字／詞對齊後產生 2 個有界字幕區段。
- Breeze：辨識出「大家好這是本機語音辨識測試今天我們要確認字幕可以正常產生」，啟用逐字／詞對齊後產生 2 個有界字幕區段。
- 最新單次 CPU smoke（含逐字／詞對齊）的載入加推論約 12.49 秒／87.34 秒，程序峰值 RSS 約 3436 MiB／5425 MiB。數值受同期封裝作業與快取影響，不構成效能保證或最低 RAM 需求。
- 原始結果、stderr、SRT 與各階段耗時保留於 `build/desktop/local-whisper/source-smoke/`。

## Build and Regression

- 完整 unittest discover：135 項通過，涵蓋新增登錄、未知引擎與路徑拒絕、裝置及熱詞驗證、配置固定、時間戳、session 重用、跨段時間偏移、checkpoint 與既有功能。
- `uv pip check`：86 個已安裝套件相容。
- 原生 release build：成功產生 App、CLI 與 helper。
- frozen runtime 診斷：移除開發 Python 路徑後，兩種 Whisper 引擎與既有 FunASR／Qwen3 可匯入，內建 FFmpeg／FFprobe 可正規化音訊。
- 第一輪 frozen Taiwan Tongues smoke 的 multiprocessing resource tracker 參數解析問題已於 frozen entry 加入 freeze_support 修正；更新後兩個模型均完成 smoke，未再出現該錯誤。
- 額外執行 `build_app.py --test` 遇到本機工具鏈 `no such module 'Testing'`，不是測試通過；未變更工具鏈或既有測試框架。

## Frozen Acceptance

- 最終封裝 helper 的兩個模型均通過 CPU 離線 smoke（Python socket 封鎖及 HF offline），各產生 2 個具有真實逐字／詞時間戳的 SRT 區段。移除開發 Python 路徑後仍可執行。
- Taiwan Tongues 單次約 13.94 秒、峰值 RSS 約 2667 MiB；Breeze 約 62.83 秒、峰值 RSS 約 3907 MiB。僅為上述短錄音的程序觀測，不是最低 RAM 保證。
- 原始結果保留於 `build/desktop/local-whisper/frozen-smoke/report.json`、同目錄各模型 JSON、SRT 與 stderr。
- `verify_whisper_batch.py` 通過原生 CLI → coordinator → 真實 worker → TXT／SRT／JSON 完整流程，兩個模型的 `auto` 均選擇 CPU，工作狀態為 completed。報告：`build/desktop/local-whisper/batch-verification.json`。
- 封裝服務提供四個模型及需求欄位，兩個新增模型均 ready。測試 App：`/private/tmp/asr-desktop-dev-_61pplhd/ASR Desktop.app`。

## GUI Acceptance

- 使用者提供 2026-10-21 11:33:35、11:34:07、11:34:13 的實際 App 截圖，已完成所見模型需求卡片的視覺檢查。Taiwan Tongues 與 Breeze 均顯示 macOS 14／Apple Silicon、CPU 支援、未提供 GPU／MPS、最低 RAM 尚未實測、需求依據連結及約 3.09 GB 下載量，並呈現已就緒。前者顯示官方建議 32 GB，後者顯示工程估算 16 GB；文字未見明顯截斷或重疊。已準備模型的額外準備空間顯示 Zero KB，與既有動態空間計算一致。
- 使用者提供 2026-10-21 11:35:35、11:35:48、11:35:58 截圖，確認 Paraformer 裝置選單保留自動／CPU／GPU，Taiwan Tongues 與 Breeze 均可選取且裝置選單只有自動／CPU。配合 native build，任務 3.1 驗收完成。
- 使用者依驗收要求操作後提供 2026-10-21 11:45:46 截圖，畫面顯示「操作已接受」，兩個新增模型維持已就緒且無錯誤。這次驗證的是已有完整資產時的 GUI 下載／修復入口；程式對 ready 模型直接回傳狀態，不重新下載或更新 verified_at。首次完整資產下載與校驗證據見 Source CPU Smoke，不將本次截圖宣稱為重新下載約 6 GB 權重。
- GUI 驗收由使用者操作及提供截圖完成；電腦控制工具的 `Sky Computer Use native pipe closed before response` 問題仍存在，未宣稱已修復。
- 任務 4.2 完成；目前為 11／11 項完成。額外 Swift Testing 工具鏈限制仍保留於上方紀錄。
