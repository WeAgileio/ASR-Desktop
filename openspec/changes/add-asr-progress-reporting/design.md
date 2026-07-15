## Context

目前 workflow 只在階段切換時送出 `phase` 與 `message`，因此 CLI 無法回答一個長任務是否仍在運作、完成了多少、還要多久。不同階段可觀測程度並不相同：FFmpeg 可回報已處理的媒體時間；模型載入通常沒有細粒度 callback；FunASR 的 callback 在整合 VAD 時可能只描述內部 batch，而不是整個檔案。若把這些訊號一律轉成百分比，顯示會精準但不真實。

本工具以 macOS、本機單一任務、中文為主英文為輔為主要情境。進度功能不得改變模型選擇、VAD/batching、辨識文字、時間戳或 transcript cache identity。

## Goals / Non-Goals

**Goals:**

- 讓每個長時間階段都有可見的開始、活動、結束或失敗狀態。
- 明確區分實測（actual）、估算（estimated）與不可量測（indeterminate）進度。
- 對音訊擷取提供基於媒體時間的真實百分比。
- 在 ASR 無全域進度訊號時仍顯示 elapsed time、heartbeat，以及有足夠歷史資料時的估算 ETA。
- 同時支援適合終端互動的動態畫面與適合 pipe/CI/log 的純文字輸出。

**Non-Goals:**

- 不重寫 FunASR 的 VAD、切片或 batch 調度來製造全域 callback。
- 不承諾模型載入百分比，也不把下載進度納入本 change；離線模型解析仍由既有模型管理邏輯負責。
- 不提供跨程序、多任務或 GUI 進度中心。
- 不計算容易誤導的跨階段單一總百分比。

## Decisions

### 1. 使用結構化 lifecycle event 作為唯一進度來源

workflow 與各 adapter 發出不可變的 `ProgressEvent`。事件至少包含 phase、status、message、elapsed time 與 `progress_kind`；可量測時另含 current、total、unit 與 ETA。status 使用 `pending`、`running`、`completed`、`skipped`、`failed`。`progress_kind` 使用 `actual`、`estimated`、`indeterminate`。

同一 phase 的 actual/estimated current 必須單調不減，且只有 completed terminal event 可以顯示 100%。錯誤路徑必須發出 failed terminal event 後再把原始例外交還既有錯誤處理。renderer 僅消費事件，不自行猜測業務狀態。

### 2. producer 與 renderer 分離

媒體層、model adapter 與 workflow 負責產生語義正確的事件；CLI renderer 負責 spinner、progress bar、顏色與換行。這讓測試可直接驗證事件，而不依賴終端畫面，也讓未來 GUI 可以沿用同一 contract。

CLI 提供 `--progress auto|rich|plain|off`。`auto` 在互動 TTY 使用 Rich 的單一 live view，否則使用 plain renderer。plain 模式不得輸出 ANSI 控制碼，並限制 heartbeat 頻率，避免長任務產生過量 log；off 僅停用呈現，不停用內部計時與效能樣本記錄。

### 3. FFmpeg 以媒體時間提供 actual progress

音訊擷取改由 FFmpeg machine-readable progress channel（`-progress pipe:1 -nostats`）取得 `out_time`，並以 ffprobe 取得的來源 duration 作為 total。百分比為 `clamp(out_time / duration, 0, 1)`，最後只在 FFmpeg 成功結束且輸出驗證通過後送出 completed/100%。stderr 保留供診斷，不與 progress protocol 混讀。

若 duration 缺失或無效，擷取仍可執行，但以 indeterminate spinner 與 elapsed time 呈現；不得以 wall-clock time 偽裝媒體百分比。

### 4. ASR callback 必須宣告全域語義才能成為 actual

ASR adapter contract 可接收 progress reporter，並宣告 callback 的 scope 與 unit。只有 adapter 能保證 `current/total` 覆蓋整個輸入音訊且 total 穩定時，workflow 才把它轉為 actual progress。

目前 FunASR 整合 VAD 的 callback 可能在每個內部 batch 重新計數，因此 Nano 與 Paraformer adapter 預設把 ASR 視為 indeterminate。應將 FunASR 原生 `tqdm` 關閉，避免重複進度條。若未來 FunASR 或其他 adapter 提供可靠的全域 callback，只需更新該 adapter capability，不必修改 renderer。

### 5. ETA 使用相容歷史 RTF，並明確標示為估算

每次成功、非快取命中的 ASR 完成後，記錄 `RTF = ASR wall time / audio duration`。效能輪廓以 model id、model revision、device/backend 與主要 runtime identity 分組，使用近期有效樣本的穩健統計值；失敗、取消、快取命中及過短而不具代表性的輸入不納入樣本。

若有相容且足量的輪廓，預估耗時為 `audio duration × historical RTF`。estimated progress 在任務真正完成前上限為 95%，ETA 與百分比都必須標示「預估」。無樣本、樣本不相容或輪廓檔損毀時，安全退回 indeterminate，不阻止字幕生成。

輪廓以原子寫入的 JSON 儲存在應用 cache 區，與 transcript cache 分離；字幕格式、語言提示等不影響輪廓 key，也不因輪廓變動造成重新辨識。

### 6. phase 狀態反映 cache 與實際工作

workflow 依序呈現輸入檢查、音訊擷取、模型準備、ASR、字幕生成與輸出寫入。若 transcript cache 讓某階段未執行，該階段發出 skipped terminal event 並附原因；不得先顯示 running 後立即假裝 100%。cache miss 則正常呈現各階段。

renderer 自己的 refresh timer 可持續更新 spinner 與 elapsed time，因此 model call 不必為了 heartbeat 建立額外辨識 thread。plain renderer 只在開始、節流後的 heartbeat、狀態改變與 terminal event 寫一行。

## Risks / Trade-offs

- **歷史 ETA 在第一次執行或模型/裝置改變後不可用。** 退回 elapsed-only，累積足量相容樣本後才顯示估算。
- **RTF 會受音訊內容與機器負載影響。** 使用近期穩健統計值、清楚標示估算，且不在完成前到達 100%。
- **FFmpeg progress protocol 增加 subprocess 管理複雜度。** 將 protocol parsing 隔離並以錄製輸出做單元測試，同時保留 stderr 與 exit-code 驗證。
- **Rich 增加直接依賴。** 只限呈現層使用，plain renderer 保持完整功能並覆蓋非 TTY 情境。
- **不重寫 FunASR batching 代表 ASR 常無真實百分比。** 這是刻意選擇，以辨識正確性與時間戳穩定性優先於視覺上的精準感。

## Migration Plan

1. 擴充現有 progress callback contract，保留既有呼叫端可忽略新增欄位的相容性。
2. 先接入 workflow lifecycle 與 plain renderer，再接入 FFmpeg actual progress、ASR capability 與效能輪廓。
3. 加入 Rich renderer 後將 CLI 預設設為 auto；非 TTY 行為仍是純文字。
4. 舊版不存在效能輪廓時視為正常冷啟動，不需資料遷移；損毀或未知版本輪廓可忽略並重新累積。

