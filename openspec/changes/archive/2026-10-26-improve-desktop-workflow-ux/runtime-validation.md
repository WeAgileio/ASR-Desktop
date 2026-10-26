# Runtime Validation

## Environment

- 日期：2026-10-25 至 2026-10-26；Apple M1 Max、macOS 26.6.2，使用本機 Xcode 工具鏈編譯 macOS 14 以上目標。
- 沒有執行 Git、提交、推送、發版或替換已安裝 App；沒有下載模型或操作使用者的正式任務。
- GUI 使用目前 App 目標編譯後的 View、Model 與資源，連結到獨立的 `ASR UX Validation.app`，以假服務資料檢查呈現與互動。這不等同封裝 App 與真實服務的端到端驗收。
- 驗證產物位於 `build/desktop/workflow-ux-validation/`；臨時 GUI 主程式來源另保存為該目錄的 `fixture-host.swift`，未加入正式產品。

## Automated Tests

### Swift

33 個測試通過：18 個既有 Core 測試、15 個 App 測試；最終編譯無新增警告。

```sh
CLANG_MODULE_CACHE_PATH=/private/tmp/asr-ux-clang \
SWIFTPM_MODULECACHE_OVERRIDE=/private/tmp/asr-ux-swift \
swift test --package-path desktop \
  --cache-path /private/tmp/asr-ux-packages \
  --config-path /private/tmp/asr-ux-config \
  --security-path /private/tmp/asr-ux-security \
  --scratch-path /private/tmp/asr-ux-build --disable-sandbox
```

預設快取位置受到沙箱限制，因此改用可寫入暫存路徑。紀錄：`swift-tests.log`。

新增／延伸測試涵蓋：

- 匯入、設定與已儲存預設值獨立，第一次載入與外部更新不覆蓋編輯。
- 所有提交欄位變更、遲到預覽、零輸出格式、零有效檔案與清除來源後的遲到探測。
- 連線失敗／能力不相容不假報佇列狀態，刷新錯誤不覆蓋操作錯誤。
- 暫停／運作中提交、接受後刷新失敗、拒絕提交保留草稿。
- 回應遺失保留同一請求識別與內容；重送不接受衝突變更。
- 查詢、換頁、查看詳情、跨頁勾選、全選快照與不同移除範圍。
- 各任務狀態的合法動作、未回收任務拒絕單筆重試、無效或估計進度、計畫輸出不冒充已交付成果。

### Shared Desktop Service

81 個既有桌面整合測試通過。使用既有 Python 測試環境，未修改服務實作。

```sh
PYTHONPATH=src /private/tmp/asr-precommit-testenv/bin/python \
  -m unittest discover -s tests/desktop -v
```

這組測試需本機 socket 與子程序，於沙箱外獲准執行，各測試使用自己的暫存資料。紀錄：`python-tests.log`。涵蓋共用任務資料、完整範圍查詢、選取 token、重試／移除、來源與成果保留、模型引用保護、排程及程序回收；不代表真實 ASR 模型與新版 GUI 已一起完成轉錄。

## GUI Verification

### Window Matrix

已留存並核對 24 張基線畫面：四分頁 × 深／淺色 × 860×640、1040×740、1440×900；圖片檔案尺寸已逐一程式核對。檔名格式：`final-<import|jobs|models|settings>-<860|1040|1440>-<light|dark>.jpg`，各有對應 `.ax.txt` 輔助使用樹。

- 最小視窗採批次／列表兩欄；寬視窗顯示三欄。長中文與英文檔名可換行，完整來源仍可查看。
- 分頁內容可捲動，主要動作、版本與品牌連結保持可達。
- 另外留存 `final-long-error-860-dark.jpg` 與 `final-empty-860-dark.jpg`，確認長錯誤、無符合結果與清除條件入口。
- 寬視窗第一次因臨時測試程式未置中而超出螢幕；已讓測試視窗置中並補拍，未將截圖裁切當成產品版面問題。
- 為在包含原生視窗裝飾的 640 點高度內操作，產品內容的最小高度調整為 580 點，保留原有 1040×740 預設尺寸。

### Observed Interactions

- 混合來源顯示一筆有效媒體的 `1:00:12` 與另一筆「找不到音軌」；預覽後顯示有效 1／無效 1，提交按鈕標示 1 個有效檔案。
- 修改遞迴設定立即使提交停用，重新預覽才可提交。
- 提交後顯示接受數、暫停佇列說明、查看剛提交批次及明確恢復入口；運作中與刷新失敗分支由 App 測試覆蓋。
- 勾選 A 與查看 B 分離；窄版詳情有返回入口，詳情補充目前勾選範圍，返回不重設條件。
- 批次選單明示整批動作不受篩選限制；移除確認顯示檔案保留說明，Escape 取消。
- 模型卡可辨識 missing、downloading、verifying、ready、failed 的狀態及相符動作；引用保護由服務測試覆蓋。
- 設定頁各組、進階選項、目前版本與更新入口均出現在可操作的輔助使用樹。
- Cmd+F 可切換至任務並聚焦搜尋；改名欄位進入時選取原名稱，Escape 可取消。
- SwiftUI Menu 在實測中未恢復鍵盤焦點，因此只將可見批次選單改用原生 NSPopUpButton。最終已確認取消改名後焦點回到「此批次操作」，直接按空白鍵可重新開啟選單；證據：`final-batch-focus-restored.jpg` 與對應 `.ax.txt`。

### Accessibility and Appearance

- 勾選框名稱包含檔名，任務狀態與時長有輔助使用值；操作錯誤的輔助使用名稱包含完整原因。
- 抽樣正常文字核心與背景像素：淺色約 15.03:1、深色約 12.02:1，均高於 4.5:1。抽樣資料：`contrast-samples.json`；未宣稱所有控制項與狀態均已完成對比量測。
- 實際啟用「減少動態效果」後操作分頁與搜尋，資訊不依賴動畫才能理解；原始設定為關閉，已還原為關閉。
- VoiceOver 曾透過首次使用入口啟用，並在啟用時檢查輔助使用樹；工具無法可靠核對實際語音內容及連續公告是否打斷，因此不以此宣稱完整朗讀驗收通過。已在系統設定核對 VoiceOver 開關還原為關閉。

## Test Host Issues

使用者提供的崩潰報告均指向獨立 `UXPreview` 測試程式，並非已安裝 ASR Desktop：

1. 偏好套件名稱與測試 App 相同，加上強制解包導致初始化崩潰；臨時程式已改用獨立偏好套件並移除強制解包。
2. 臨時 App 漏複製 Swift 品牌資源包，觸發 Bundle.module 斷言；已補入資源。既有正式 build_app.py 原已包含此步驟。

修正後可持續操作與截圖。這些報告不能用來推論正式安裝包已驗證通過或發生相同崩潰。

## Live Service Verification — 2026-10-26

使用者解鎖後，另以 `ASR UX Live Validation.app` 連到隔離的真實 coordinator/control socket；GUI 使用正式 DesktopModel 與 ServiceClient，沒有取代正式安裝 App。環境與來源見 `live-environment.json`、`live-host.swift`。更新 fetch 仍使用空清單 fixture，避免此次 UI 驗證對外下載；HTTP 與版本處理另由既有更新測試覆蓋。

- 真實 FFprobe 探測混合資料夾：1 個一秒有效 WAV、1 個無法解碼檔案。預覽列出有效 1／無效 1，僅提交有效來源。
- 先在暫停佇列提交，顯示「請明確恢復佇列」；手動恢復後再次提交，顯示「已加入運作中的佇列」。兩次均顯示缺模型等待，沒有下載模型。證據：`live-paused-submit.*`、`live-running-submit.*`。
- 原有 120 筆加上兩次提交後顯示 122 筆；全選顯示「122 筆、所有頁」，第二頁顯示 101–122，選取仍保持。證據：`live-cross-page.ax.txt`。
- 歷史失敗測試項目重試後，服務回報重試 1、略過 0，狀態改為等待指定模型；隨後單筆移除確認顯示 1 筆及檔案保留說明，接受後範圍由 122 降為 121。證據：`live-retry.ax.txt`、`live-remove.ax.txt`。
- 歷史完成測試項目的 Finder 按鈕確實開啟隔離 outputs 目錄並選取 TXT、SRT。證據：`live-finder.ax.txt`。歷史完成／失敗狀態是刻意建立的測試資料，並非此次真的執行 ASR 推論。
- 真實 CLI 將預設 script 改為 original，GUI 設定頁顯示原文／已儲存 original，匯入草稿仍維持台灣繁體；CLI 暫停佇列後 GUI 標頭同步變成已暫停。證據：`cli-settings.json`、`cli-queue.json`、`live-cli-and-updates.*`。
- 點選檢查更新後，最後成功檢查時間改為此次時間，版本／更新／CLI 入口均保留。此項驗證 UI 與更新狀態串接，未宣稱此次真實 GitHub 網路請求已驗收。
- 使用者明確要求「VoiceOver 可以都先不用測試」，因此本輪所有 VoiceOver 實機測試排除，不再作為完成的阻礙；VoiceOver 已核對關閉。
- 系統鍵盤導覽原始值為關閉，Tab 會略過一般按鈕；使用者回覆「鍵盤流程也先略過」，因此沒有啟用，完整鍵盤流程本輪排除。Cmd+O、Cmd+F、原生選檔對話框鍵盤操作已驗證。

### GUI Lifecycle

已透過原生介面退出 live GUI 測試 App，並以程序查詢確認測試 GUI 已不在執行。之後 CLI 仍能取得同一服務 PID 89225、運作中佇列與第一頁 100 筆任務；另以唯讀資料庫計數確認全部 121 筆紀錄；來源及歷史成果檔案仍存在。關窗後讀取 GUI 會由 UI 工具再次喚起視窗，因此最後採退出 GUI 後以 CLI／程序核對，避免將重新開啟誤當關閉失敗。證據：`before-close-*.json`、`after-close-*.json`。此項確認前景 App 不持有服務生命週期，沒有將缺模型等待狀態當成真的推論中。

## Remaining Verification

依使用者調整後的本輪範圍，追蹤進度為 **19/19**。完整鍵盤流程與 VoiceOver 實機測試依使用者 2026-10-26 明確要求略過，沒有記為測試通過；相關功能實作與既有局部驗證保留。其餘本次真實服務觀察列於上方。

完整控制項的所有狀態對比，以及真實模型執行中的關窗後持續推論，仍未驗證；本輪正常文字樣本達標，服務排程與程序生命週期另有 81 個測試覆蓋。不將這些限制隱藏或以成功編譯代替。

本輪隔離服務已於驗證後停止，未停止使用者的正式服務；系統設定檢查已結束，鍵盤導覽維持原始關閉值。使用者選擇略過鍵盤流程後，已更新 4.3 的本輪驗收範圍；未變更系統設定或將略過流程記為通過。
