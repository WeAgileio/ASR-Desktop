# Verification

## 已通過

- `python3 desktop/scripts/build_app.py`：release 建置與 arm64 架構檢查通過，產出 `build/desktop/ASR Desktop.app`。
- `swift -module-cache-path build/desktop/cache/swift desktop/scripts/build_brand_assets.swift`：兩份 PDF 向量素材生成成功。
- 以 `cmp` 確認專案 SVG 與使用者附件完全相同。
- 以 CoreGraphics 將兩份 PDF 渲染成 320 × 320 PNG 並檢視：輪廓、原始比例與綠色圓點正確，深色／淺色背景皆可辨識；PDF 頁面均為 160 × 160。
- 實際重試發現 SwiftUI 名稱搜尋未顯示 PDF；改以明確資源 URL 載入 NSImage 後，已在主視窗截圖確認 Logo 正常顯示。
- 資源 bundle 改為 Contents/Resources，避免 App 根目錄資源造成簽章失敗；獨立暫存 App 通過 codesign --verify --deep --strict。
- 實際點擊來源連結，系統預設 Chrome 開啟 https://karakuri.tech/zh-tw/，來源網站正確。
- 依使用者後續回報加入 Dock／Finder 圖示：ICNS 包含 16–1024 像素資源，解出 256 像素 PNG 檢視確認 Logo 及綠色圓點正確。
- 含 CFBundleIconFile 與 ICNS 的 App 已重新建置、通過簽章驗證並透過 Computer Use 啟動。驗證副本位於 /private/tmp/asr-desktop-dev-5ro5i1nb/ASR Desktop.app。
- `python3 -m py_compile desktop/scripts/build_app.py`：通過。
- `openspec validate add-karakuri-branding --strict`：通過。

## 最終驗收結果

2026-10-21 使用者接手剩餘人工驗收後回覆「驗收通過」。所有任務已完成（9/9）。

- Task 2.1：匯入、任務、模型、設定四個分頁在深淺色外觀下均保留正確 Logo 及來源區域；裝飾 Logo 未重複出現在輔助使用樹。
- Task 2.2：滑鼠點擊已由代理確認網站目的地；新增 `.focusable()` 後，Tab 聚焦已由代理確認。剩餘鍵盤啟用及連結輔助使用驗收由使用者接手並確認通過。
- Task 2.3：在 860 點寬、640 點內容高度的最小視窗觸發延遲 intake.preview，輔助使用樹出現 busy indicator；截圖確認忙碌指示器、兩行長訊息及完整來源連結同時可見。證據：build/desktop/branding-verification/light-busy-confirmed.png。
- Task 3.1：以相同 App 執行檔與封裝資源建立獨立暫存 App，套用禁止網路及原始 build／attachments 目錄讀取的驗收沙箱。完整主視窗正常啟動，Logo 與來源文字顯示正確；原始目錄讀取明確回報 Operation not permitted，網路探針亦失敗。
- Task 3.2：隔離服務測試已確認 queue.resume 可讓畫面由已暫停變成運作中；使用者進一步接手分頁切換及暫停／恢復操作，確認通過。
- Task 4.1：使用者另行確認「Dock 圖示有正常顯示」。

深色測試取得使用者同意，完成後已將系統還原為原本的淺色。控制測試使用獨立 Unix socket 與模擬服務，不操作實際轉錄佇列。

## 驗收證據與限制

截圖與操作紀錄位於 build/desktop/branding-verification/。其中 dark-busy.png 實際未包含忙碌指示器，僅作為深色最小視窗及長訊息證據；忙碌驗收以 light-busy-confirmed.png 為準。

介面工具曾反覆斷線或長時間無回應；最終剩餘人工項目依使用者的驗收確認完成，並非代理宣稱已獨立操作通過。未進行 Git 提交、發版或 OpenSpec 封存。
