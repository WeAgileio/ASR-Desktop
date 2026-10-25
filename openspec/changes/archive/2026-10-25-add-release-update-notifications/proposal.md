# Proposal

## Why

桌面使用者目前需要自行查看 GitHub 才知道是否有新版本；即使已有 Release，也可能缺少可下載的 DMG。需要把可安裝版本的提醒與維護者補包流程串起來，讓使用者自行決定何時下載及安裝。

## What Changes

- 主視窗底部常駐顯示目前 App 完整版本（包含 beta），設定頁同步顯示；不需連網或執行更新檢查即可查看。

- 新增桌面背景更新檢查及設定頁「檢查更新」，依本專案已發布 Release、版本順序與相容安裝包判定可更新版本。
- 顯示目前／候選版本及更新說明，提供「前往下載」、「稍後提醒」、「略過此版本」。前往下載只開啟該版 GitHub Release 頁，不下載、替換 App、停止服務或改動轉錄資料。
- 提案預設：自動檢查可關閉，啟動時距上次自動嘗試至少 24 小時才檢查；測試版可收到較新的測試版及正式版，正式版預設只收到正式版。手動檢查可查看已略過版本。
- 擴充既有 GitHub Actions：保留測試標籤觸發發布與手動只建置流程，新增指定既有標籤的補包模式。從標籤對應來源打包；Release 不存在時建立，已存在時保留內容並補上缺少的 DMG／校驗檔。
- 補包不得覆寫既有資產、移動標籤或把目前分支冒充舊版；發布後核對資產與校驗值，重跑能辨認已完成結果。

## Capabilities

### New Capabilities

- `desktop-release-updates`：依可安裝的 GitHub Release 提醒新版，處理版本通道、檢查狀態及使用者提醒偏好，以瀏覽器交接下載。
- `desktop-release-packaging`：維護者按既有版本標籤建置、驗證及補齊 Release 安裝資產，保留版本來源與既有發布內容。

### Modified Capabilities

無。沿用 `macos-desktop-transcription` 的安裝平台、維護資料保留與背景工作契約；本變更不加入自動安裝或修改其更新／回退行為。

## Impact

- Swift：`desktop/Sources/ASRDesktopCore` 的版本與 Release 判定、網路檢查及提醒偏好；`ASRDesktopApp` 的設定頁與提示，加入可替代網路／時間／瀏覽器的測試。
- 發布：`.github/workflows/desktop-release.yml`、`desktop/scripts/package_release.py` 及必要的發布驗證腳本／測試；保留現有 runtime、媒體工具、DMG 驗證流程。
- 版本來源：`pyproject.toml`、App 內的 `ASRDesktopReleaseVersion` 與 Release tag 格式需一致對照，不以固定為 1 的 `CFBundleVersion` 判斷更新。
- 文件：桌面操作指南及維護者發布說明；讀取 GitHub 公開 Release metadata，不上傳音訊、任務、模型或本機路徑，不在 App 內嵌 GitHub token。
- 不新增自動更新框架；不包含 Apple Developer ID 簽署／公證、正式版發行流程擴張或本次實際發布。現有 beta ad-hoc 打包限制保留，無法由舊標籤可靠建置時明確失敗。
