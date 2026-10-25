# Design

## Context

動機與範圍見 [proposal.md](proposal.md)。本變更跨 Swift UI／網路與 GitHub Actions 發布，需先固定版本與資產契約。

已查證本機程式：

- `pyproject.toml` 為 `0.2.0b2`；`build_app.py` 寫入完整 `ASRDesktopReleaseVersion`，但 `CFBundleShortVersionString` 去掉 beta，`CFBundleVersion` 固定為 1。
- `.github/workflows/desktop-release.yml` 已有 `v*-beta.*` tag push 與 workflow_dispatch；手動模式只上傳 14 天 Artifact，publish job 僅在 push 執行。
- `package_release.py` 只接受 `X.Y.ZbN`，產生 `ASR-Desktop-vX.Y.Z-beta.N-arm64.dmg`、`.sha256` 與 README 該版本說明；已有完整建置、ad-hoc 簽署、runtime／DMG 驗證。
- 現有 publish 直接 `gh release create`，未處理已存在 Release。App 沒有更新檢查介面；設定頁與 service 控制可作為加入入口。
- 主規格 `macos-desktop-transcription` 已要求更新保留資料與不干擾背景工作。本次只開下載頁，不接管安裝或 helper 替換。
- 未查證遠端目前資產清單或 Actions 實際執行結果；不據本機 workflow 存在宣稱 GitHub 已成功發布。

## Goals / Non-Goals

**Goals:** 更新判定可用固定資料測試；網路檢查獨立於轉錄 helper；手動補包可重跑且來源可追溯；保留原手動只建置習慣。

**Non-Goals:** 自動下載／替換／重啟、Sparkle、憑證管理、正式簽署公證、強制更新、模型更新、公開穩定版打包流程擴張及任意舊 tag 相容修補。

## Decisions

### 1. 版本與安裝資產作為共同契約

讀取 App 的 `ASRDesktopReleaseVersion`；只接受嚴格的 `X.Y.Z`、`X.Y.ZbN` 與 GitHub `vX.Y.Z`、`vX.Y.Z-beta.N`，正規化為數字三元組及 beta 序號。正式版高於同版 beta；拒絕不支援的 rc／任意文字，而不猜測。release 的 prerelease 標記須與 tag 一致。不同表示但相同正規化版本不得重複提醒；歧義重複版本回報資料異常。

目前桌面資產契約為 Apple Silicon、macOS 14+，精確名稱 `ASR-Desktop-<tag>-arm64.dmg`，uploaded 且大小非零；原始碼 zip／tar 與僅名字含 dmg 的其他資產不算。對不支援平台不提示可安裝。本輪不引入最低系統 metadata 新格式；未來發布若提高最低系統，必須先擴充相容性 metadata／契約，不能沿用本規則誤報相容。

提案預設採既有安裝版決定通道：beta 使用者可收到 beta／正式版，正式版僅正式版；先不新增通道設定。這可保留目前 beta 發布方式，避免 `/releases/latest` 漏掉測試版。版本比較優於發表日期，能避免補舊版 Release 被當成更新。

目前版本在 App 啟動時從 bundle 讀取，共用同一解析與顯示值：例如 `0.2.0b2` 顯示為 `v0.2.0-beta.2`，正式版顯示為 `vX.Y.Z`；缺失／不支援格式顯示「版本未知」。主視窗共用底部加入此標示，設定頁同步呈現，並保留既有來源網站連結及操作狀態訊息。版本標示與網路檢查狀態獨立，任務刷新或遠端候選變更不覆寫它。最小視窗尺寸以版面調整保持版本可讀，避免擠掉原有控制。

### 2. Swift 客戶端唯讀檢查

在 ASRDesktopCore 放置小型版本／Release 資料型別與可測的候選選擇；使用系統 URLSession 非阻塞讀取固定 `WeAgileio/ASR-Desktop` 的公開 REST releases 清單，不加第三方更新套件或要求登入。

分頁追蹤到結束才宣告沒有可用更新，限制總請求時間、頁數及回應大小，達上限回報結果不完整。只跟隨同一 GitHub API 儲存庫路徑的分頁；請求設定有限 timeout，處理 403／429 的 Retry-After 或 reset 時間，禁止立即重試迴圈。背景與手動檢查共享一個進行中的請求，關閉自動檢查或新狀態不得被過期回應覆蓋。

固定更新來源與瀏覽器目的地：只接受 `https://github.com/WeAgileio/ASR-Desktop/releases/tag/<candidate-tag>` 的有效編碼 URL；可由固定 owner/repo/tag 組出，不執行 Release 本文的 HTML／腳本。說明以安全文字呈現並有長度上限，完整內容由下載頁查看。

### 3. 提醒狀態留在 App 偏好

以 UserDefaults 保存自動檢查開關（預設開）、lastAutomaticAttempt、lastSuccessfulCheck 與略過的正規化版本，不修改 SQLite／任務設定 schema。注入時鐘、偏好儲存、HTTP transport 及開瀏覽器介面供測試；不建立泛用更新框架。

App 啟動後若距上次自動嘗試至少 24 小時才送請求，記錄嘗試時間避免離線每次啟動重試；常駐 App 不新增週期輪詢。手動檢查略過 24 小時限制，但仍遵守 API 退避。稍後提醒只關閉提示，不抹除檢查時間；略過抑制該版自動提示，手動查詢仍顯示候選。

設定頁展示檢查中／可更新／沒有可用更新／沒有發布版本／無法判斷／失敗，及最後成功時間；背景錯誤只更新狀態，不彈阻斷視窗。「前往下載」呼叫系統預設瀏覽器並檢查開啟結果，不代表更新成功，亦不呼叫 queue／service mutation。

### 4. 擴充既有工作流程而非另建發布線

workflow_dispatch 加入明確 `mode`（build-only 預設、repair-release）與 `release_tag`。tag push 仍走既有 beta 發布；repair-release 必填既有 annotated beta tag。目標字串透過參數／環境傳遞並先驗格式，不能插入 shell 程式文字。

工作流程定義與補包控制腳本來自執行該 workflow 的已選 revision；產品程式及其鎖定依賴、打包腳本從目標 tag 的另一個 checkout 建置，記錄兩者 commit。這允許新控制流程處理舊版，卻不把新產品檔案複製進舊來源。若該 tag 的打包工具缺失或失敗，要求維護者另行處理，不靜默以 main 打包。補包選擇與權限在 Actions UI 明確呈現。

解析目標 tag 後記錄 tag object 與 commit；核對來源版本、README release notes、產物 Info.plist 完整版本。發布前重新核對 tag 未移動。補包與 push 以目標版本組成相同 concurrency group，且 publish 前再讀資產處理競爭。build-only 使用 read 權限，發布 job 才有 contents:write，執行產品建置的步驟不取得發布 token。

### 5. 依既有資產狀態決定補包策略

| 目標狀態 | 行為 |
| --- | --- |
| 無 Release／無 DMG 與 hash | 由 tag 建置驗證；建立 Prerelease 或補上兩檔 |
| 有 DMG、無 hash | 下載既有檔至隔離路徑，驗證 DMG、內含版本／平台，按該檔產生 hash；不替換 DMG |
| 無 DMG、有 hash | 建置後須與既有 hash 相符才上傳；因簽署等造成不可重現時回報衝突 |
| 兩者齊全 | 下載核對 hash 與 DMG 版本／封裝；相符則 no-op，不符則失敗 |

不得使用 `--clobber`，不得修改已有 Release 標題、本文、draft／prerelease 標記或其他資產。不存在的 Release 以 tag 版本說明建立 Prerelease；已存在但通道標記不符時回報衝突，不自動修正。草稿可以補資產但保持草稿，App 的公開檢查不把它當作可更新版本。

上傳後重新下載核對資產 SHA-256、檔名及目標 Release，記錄來源 commit、資產 ID、尺寸、摘要與連結。若只上傳一檔即失敗，保留成功資產並在下一次依狀態續做；不能把部分成功回報成完整發布。SHA-256 用於一致性，並不聲稱取代正式簽署／公證或供應鏈驗證。

### 6. 驗證分層並區分發布授權

原生測試使用固定 Release 分頁與錯誤回應、假時鐘／偏好／瀏覽器，不依賴公開版本恰好存在。發布控制用假 GitHub 回應與固定資產驗證 no-op、衝突、部分失敗、草稿保留及來源鎖定，沿用實際 DMG 建置與驗證腳本。

GUI 以隔離環境演練可更新／略過／稍後／離線、瀏覽器開啟與轉錄不受影響。Actions 的實際 workflow_dispatch 與 Release 寫入另需維護者授權目標 tag／測試儲存庫；未執行時相關驗收保持未完成。建立提案或日後實作不代表已授權發布。

## Risks / Trade-offs

- [公開 API 限流或網路失敗] → 24 小時背景節流、手動結果可見、退避與有界分頁，不偽稱最新版。
- [同名舊版本重建位元組不同] → 保留既有 DMG，hash 由既有檔計算；已有 hash 衝突則停止，不覆寫。
- [舊 tag 依賴／Xcode 不再能建置] → 明確標示該 tag 的失敗與報告，不能承諾補包任何歷史版本。
- [現有 runner／Xcode 可用性] → 實作時確認 macos-15 的實際 arm64 與 Xcode 路徑；不以移除架構或版本檢查繞過失敗。
- [ad-hoc DMG 仍可能被 macOS 阻擋] → 沿用現有測試版說明，不宣稱已公證，不引導停用系統防護。
- [下載頁不等於完成安裝] → 按鈕命名為「前往下載」，不顯示更新成功，不自動停止背景轉錄；操作指南沿用更新前停止服務與備份步驟。

## Migration Plan

1. 先完成版本／資產判定及網路錯誤測試，再接 App 提醒與偏好，不改既有資料庫。
2. 為現有 workflow 加入明確模式與補包控制，保留 build-only 預設；測試發布判斷後驗證實際 DMG。
3. 在獲授權的測試目標執行補包／重跑驗收，再由維護者決定正式目標發布；首次含更新提醒的 App 仍須手動安裝。
4. 回退 App 或 workflow 不需遷移資料；更新偏好可被舊版忽略，已發布資產不因程式回退而刪除。
