# 非 GUI 驗收 — 2026-10-24

本紀錄對應任務 7.5、7.4、7.2、7.3 的非介面部分，不替代實際畫面驗收。程式測試使用隔離 Python 3.9.6 環境；安裝版 App 演練使用其內建 runtime，不依賴該測試環境。未進行模型品質評測。

## 7.5 錯誤與修復

| 情境 | 證據與結果 | 尚待 GUI 核對 |
| --- | --- | --- |
| 模型空間不足、離線、checksum 錯誤 | test_models 驗證未就緒、容量不足不開始下載，以及恢復後可重試 | 錯誤文字、修復入口 |
| 輸出途中磁碟滿 | test_exports 注入 ENOSPC，重試保留已交付檔案並補齊輸出 | 釋放空間後重試提示 |
| 不安全 socket 目錄、其他使用者連線 | test_coordinator_bootstrap 驗證拒絕連線／操作，不靜默放寬權限 | 介面提示；不等同系統背景權限驗收 |
| runtime 缺失／損壞 | 複製完整 App 至暫存目錄，移走 runtime 與置換無效執行檔，各回傳 diagnose 退出碼 3、ready=false；還原後退出碼 0、ready=true | GUI 診斷與重新安裝提示 |

錯誤修復與服務測試合計 **22 項通過**：

```sh
PYTHONPATH=src build/desktop/test-env/bin/python -m unittest \
  tests.desktop.test_models tests.desktop.test_exports \
  tests.desktop.test_coordinator_bootstrap -q
```

初次測試缺少 psutil；在隔離環境安裝專案鎖定的 psutil==7.2.2 後通過。runtime 演練結果位於 `build/desktop/runtime-repair-verification.json`；沒有修改安裝位置的 App。

## 7.4 操作對照

| GUI 入口 | CLI／服務操作 | 非 GUI 證據 |
| --- | --- | --- |
| 暫停／恢復佇列 | queue pause／resume | scheduler 測試確認目前任務繼續、下一筆等待 |
| 取消／重試 | jobs cancel／retry | scheduler 測試確認程序群組回收與中斷後明確重試；workspace 驗證來源變更拒絕沿用 |
| 模型管理 | models list／download／verify／remove | models／workspace 測試涵蓋完整性、重試、占用模型不可刪除 |
| 預設值 | settings show／set | 新增測試確認舊任務保留 auto、TXT/SRT，新任務採用 CPU、JSON 輸出計畫 |
| 校準 | device calibrate／explain | workspace 測試確認同一固定來源建立 CPU／GPU 依序工作；未執行真實模型校準 |
| 背景服務 | service start／status／stop | bootstrap、既有隔離生命週期演練；GUI 關閉視窗的實際行為仍待驗收 |

## 7.2 批次匯入

安裝版 CLI 與真實 FFprobe 在獨立資料／socket 目錄演練：輸入包含中文及空白檔名的一秒 WAV、子目錄 WAV、無效文字檔，以及重複來源。非遞迴有效數為 1，遞迴為 2；duplicate 與 invalid 被排除。提交後兩筆工作因缺模型而 blocked，輸出計畫存在；整批取消後為 cancelled=2。佇列保持暫停，沒有轉錄或下載。服務已停止並清理暫存資料。

結果位於 `build/desktop/intake-cli-verification.json`。拖入、多選、資料夾選取及預覽畫面仍待 GUI 驗收。

## 7.3 任務與進度資料

重現並修正 `jobs.list` 的 batch_id 篩選錯誤：先前 jobs／total 僅包含指定批次，counts 卻包含所有批次。新增兩批次回歸案例，一批 blocked、另一批 cancelled，確認篩選後只回傳該批的計數；未篩選時仍保留全域計數。

既有進度測試涵蓋事件格式、明確 ETA、缺 ETA 不捏造估計、估計進度、失敗後繼續下一筆，以及大量進度事件仍保留最後狀態。這些是資料／renderer 層證據，不代表 SwiftUI 的 actual／estimated／indeterminate、裝置理由、結果開啟及跨入口畫面已驗收。

操作、匯入、計數及進度測試合計 **34 項通過**：

```sh
PYTHONPATH=src build/desktop/test-env/bin/python -m unittest \
  tests.desktop.test_workspace tests.desktop.test_scheduler \
  tests.test_progress_performance -q
```

本次 workspace 修正尚未重新封裝到已安裝 App。7.1–7.5 仍維持未勾選；總進度為 38/45。

## 使用者驗收更新 — 2026-10-24

使用者已確認 GUI 全部驗收完成，7.1–7.5 據此完成。本文其餘「待 GUI 驗收」描述保留為非 GUI 測試當時的範圍紀錄；目前整體進度為 43/45，剩餘 8.3、8.4。
