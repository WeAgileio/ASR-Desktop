# Runtime validation — 2026-10-25

## 範圍與環境

本機 macOS 26.6.2 arm64，Swift 6、Python 3.11.15 的 locked packaging-env。未執行 Git 指令、push、tag、GitHub Release 寫入或遠端 Actions。更新狀態由 App 層持有，各視窗共享同一檢查與偏好；調整後重跑 19 項原生測試通過。`improve-desktop-interface` 由使用者移除，本次未重新建立或修改該提案。

## 自動測試與建置

- `build/desktop/packaging-env/bin/python desktop/scripts/build_app.py --test --scratch-path /private/tmp/asr-update-swift`：18 Core + 1 App 測試通過。版本比較、通道／資產、惡意 URL、文字說明、第二頁候選、空清單、未完成分頁、逾時 transport、頁數／大小上限、403／404／429、離線、偏好跨重啟、24 小時節流、略過、同時檢查與過期回應均有固定資料測試。
- `PYTHONPATH=src build/desktop/packaging-env/bin/python -m unittest discover -s tests/desktop -v`：80 項通過。第一次沙盒執行受 socket／psutil／程序群組權限限制失敗；以許可的隔離測試環境重跑成功。紀錄 `/private/tmp/asr-update-python-tests-unrestricted.log`。
- 新增 `test_release_pipeline.py` 最終 8 項測試（全套 80 項後再補驗 build-only 禁止發布，8 項相關測試重跑通過）：非法／輕量 tag、目標版本／說明／工具缺失、移動 tag、四種資產狀態、保留草稿／說明／其他資產、hash 衝突、零大小／未完成／重複資產、部分上傳重跑、競爭上傳及下載內容不一致。發布最終再比對已下載資產 ID／size，失敗寫入 publication.json 與 job summary。
- Workflow YAML 以 `yaml.BaseLoader` 解析，核對手動預設 build-only、publish 條件及 read/write job 權限。這是本機結構檢查，不代替 GitHub Actions 實跑；本機無 actionlint。
- `openspec validate add-release-update-notifications --strict` 通過。

## DMG 與 runtime

- `package_release.py --reuse-runtime`：以來源指紋相符的 frozen runtime 重用，重新建置原生 App、收集 notices、ad-hoc 簽署、建立並驗證本機 beta DMG。無遠端發布。
- `verify_runtime.py`：移除開發 PATH／Python 環境後，frozen runtime ready，ffmpeg／ffprobe 完成雙聲道 44.1kHz 至單聲道 16kHz 轉換。
- 既有 `/private/tmp/asr-upgrade-acceptance/ASR-Desktop-v0.2.0-beta.2-arm64.dmg` 以 `verify_dmg.py --expected-version 0.2.0b2` 唯讀掛載，完整版本、macOS 14 最低版本、arm64、簽署、原生依賴與 relocated runtime 通過。
- 以同一舊 DMG 位元組執行 `release_pipeline.verify_files` 補 SHA-256，原檔摘要保持 `3423607e8c9a9f1aa26f149b2c1118107e6d090c093143df239f78abc7c78b59`，校驗檔位於 `/private/tmp/asr-update-hash-repair/`。
- 預期版本改為 `0.2.0b3` 時拒絕舊 DMG並正常卸載；損壞的 `/private/tmp/asr-update-corrupt.dmg` 被 hdiutil 拒絕。錯誤紀錄 `/private/tmp/asr-update-wrong-version.log`、`/private/tmp/asr-update-corrupt.log`。

## 隔離 GUI 觀察

使用 `/private/tmp/asr-update-gui/ASR Update Validation.app`，獨立 bundle ID `io.asrsrt.update-validation` 與 run/data/cache。測試副本只替換 Release fetch 為固定 JSON／延遲／離線錯誤；產品無測試開關，不更動使用者正式資料。UI 透過 CUA 操作。

測試副本最初將與 bundle ID 相同的名稱傳給 `UserDefaults(suiteName:)!`，導致 nil unwrap 啟動崩潰（使用者提供的 16:29 報告）。已改為該獨立 App 的 `.standard`，重新簽署後多次啟動正常。此強制解開只在暫存驗收副本，未加入產品程式。

觀察通過：

- 無發布顯示「目前沒有可下載版本」；相同版本顯示「沒有可用更新」。
- 15 秒受控延遲期間顯示 spinner／「正在檢查更新」，按鈕 disabled，仍可切換任務頁。
- 提示列出目前 `v0.2.0-beta.2` 與候選 `v0.3.0-beta.1`、測試版通道、文字說明；候選不覆寫本機版本。
- 「略過此版本」與「稍後提醒」關閉 sheet；手動查詢可再次顯示已略過版本。
- 自動檢查關閉後重啟仍關閉，保留最後成功時間。
- 無效 JSON／受控離線顯示失敗並保留上次成功時間，不顯示最新版。其後產品將 URLError 改為中文連線／逾時訊息。
- 停止隔離 helper 後底部顯示未連線，版本仍可讀；手動更新檢查仍成功完成。
- 視窗縮至約 860 × 640 內容大小，版本、來源連結及兩行錯誤仍可見；匯入／任務／設定切換保持同一版本。
- 移除隔離 bundle 完整版本欄位後，底部及設定均顯示「版本未知」，手動查詢顯示無法判斷，無候選。
- 以隔離 bundle `0.2.0b1` 與固定 `v0.2.0-beta.2` 回應點擊「前往下載」，Chrome 實際新增 `https://github.com/WeAgileio/ASR-Desktop/releases/tag/v0.2.0-beta.2` 分頁；App 沒有自動下載或安裝。

## 工作不受影響

以本次隔離 coordinator 注入受控 worker 與模型就緒回應；不測辨識模型品質。工作 `job-495c28fdb73242b289c8aceaddd8f825`／attempt `attempt-aa4a42d2699f4baabd3eb0d48ba9c964` 在檢查、提示與實際瀏覽器交接前後仍為 running，除正常 progress 外所有 job 欄位完全相同。models.list、settings.show、queue.status 相同，service PID 相同。釋放受控 worker 後工作 completed。快照：`/private/tmp/asr-update-gui/{before,after,completed}.json`。驗收結束後退出測試 App 並停止隔離服務。

## 尚未通過／不可推論

- 5.2：尚未取得並執行維護者授權的測試 repo／annotated beta tag；沒有 Actions run／Release 寫入驗收連結。macOS runner 實際架構與 Xcode 安裝必須由遠端 job 證明。
- 5.3：候選到瀏覽器的交接已用固定 Release 資料測試，但尚未從真實 Release 下載並驗證其 DMG 後完成同一條端到端路徑，保留未完成。不能把本機 DMG 或模擬 asset 清單當成已發布資產。
- 本機 GUI／DMG 驗收不代表 macOS 14 實機或正式 Developer ID 簽署／公證通過。

## 最終交付產物

最後 App 共用狀態修正後，再次執行原生 19 項測試與 `package_release.py --reuse-runtime`，均成功。最終 DMG 的唯讀掛載／簽署／arm64／relocated runtime 驗證通過。這是本機測試包，沿用專案目前 0.2.0b2 版本，未宣稱與遠端既有 tag 的位元組相同，亦未上傳。

`eaab4bab0a8e4cf1a16b1cdf7170d0560127add393ffdf3580def88414bc4db2  ASR-Desktop-v0.2.0-beta.2-arm64.dmg`

## 遠端驗收進度（2026-10-25，使用者明確授權）

使用者授權 `WeAgileio/ASR-Desktop`／`v0.2.0-beta.2` 的 Actions 補包，並另行確認在獨立 checkout 執行 clone → pull → 建立 `codex/validate-release-updates` → commit → push 的 Git 流程。只提交 workflow、release_pipeline.py、verify_dmg.py 與補包測試四檔；控制提交 `9ac2989babf0a304674c80c79d510268bfe385a3`，未修改 main 或 tag。

執行前發現 Release 已有完整兩檔：DMG asset ID `661940571`，465061412 bytes；SHA-256 asset ID `661940569`，102 bytes。annotated tag object `b820c66995e1834477a8790fac6df47486299ded` 指向產品 commit `09e37942448ceaad1cbbd3c597e532016c3147bd`。未刪除既有資產以製造缺包。

從真實 Release 下載兩檔至 `/private/tmp/asr-release-remote-verification`，SHA-256 `3423607e8c9a9f1aa26f149b2c1118107e6d090c093143df239f78abc7c78b59` 符合發布校驗檔；以 `verify_dmg.py --expected-version 0.2.0b2` 通過唯讀掛載、完整版本、架構、簽署、原生依賴及 frozen runtime 驗證。

- build-only：[Actions 40179124566](https://github.com/WeAgileio/ASR-Desktop/actions/runs/40179124566)
- repair-release：[Actions 40179129571](https://github.com/WeAgileio/ASR-Desktop/actions/runs/40179129571)

真實 App API 驗收遇到設計前提不成立：GitHub API 確認此 repo `private: true`／`visibility: private`。使用未替換 ReleaseClient 的隔離 App（僅 bundle 版本模擬為 0.2.0b1）收到 HTTP 404，UI 正確顯示檢查失敗。維護者 gh 的登入權限不代表未攜帶 token 的產品 App 可存取，因此 5.3 保持未完成。未公開儲存庫、未把維護者憑證嵌入 App。隔離 App 與服務已結束。

首次 repair-release 成功。第二次重跑 [Actions 40179291885](https://github.com/WeAgileio/ASR-Desktop/actions/runs/40179291885) 亦成功；兩次 publication.json 完全相同，資產 ID、size、SHA-256、來源 commit 與 tag object 均保持。runner 記錄 `macos-15-arm64`、Xcode 16.4 (16F6)、Swift 6.1.2，證據 `/private/tmp/asr-release-repair-first.log`。兩次皆為既有資產齊全的 no-op 驗證，不可替代缺 DMG 的真實上傳情境，故 5.2 仍保留未完成。

build-only 首次執行的 Python／Swift／DMG 內容驗證已完成，但產品 verify_dmg.py 的 `hdiutil detach` 回報 Resource busy（exit 16），TemporaryDirectory 清理已掛載唯讀檔案又引發 Errno 30，整個 run 因此失敗；publish job skipped，未產生可宣稱成功的 Artifact。紀錄 `/private/tmp/asr-actions-build-failure.log`。已重跑失敗 job 一次，以區分暫時占用與可重現問題。

build-only 的第二次 attempt 成功（同一 [run 40179124566](https://github.com/WeAgileio/ASR-Desktop/actions/runs/40179124566)）：產品測試與打包、控制端掛載／checksum 驗證、Artifact 與報告上傳全部 success，publish skipped。首次卸載占用沒有在此次重跑重現；不據此宣稱已根治間歇性卸載問題。最終再次核對既有 Release ID `419351613` 與兩個資產 ID／size 均未改變。

本輪完成的驗收子項：遠端 arm64／Xcode、build-only 不發布、資產齊全補包及重跑、遠端 SHA-256／版本／DMG 有效性。5.2 尚缺真實「缺 DMG」上傳情境；5.3 因私人 repo 的匿名 HTTP 404 未通過。兩項均保留未勾選。已向使用者提出發布來源選擇，尚未取得設計決定；沒有擅自公開來源碼、另建公開庫、加入 token 或放寬驗收條件。

## 公開發布來源後的端到端驗收（2026-10-25）

使用者明確確認將 WeAgileio/ASR-Desktop 整個儲存庫及所列原始碼、歷史、Release、Actions 範圍公開。執行 `gh repo edit WeAgileio/ASR-Desktop --visibility public --accept-visibility-change-consequences` 成功，API 核對 `private: false`、`visibility: public`。不帶 token 的 urllib 請求至產品相同 Release endpoint 回傳 HTTP 200，清單包含 v0.2.0-beta.2。

隔離 App `/private/tmp/asr-live-release-check/ASR Release Check.app` 使用產品原有 ReleaseClient，無 fixture／替代 transport／token；僅本機 bundle 完整版本模擬較舊 0.2.0b1。手動「檢查更新」成功顯示目前 v0.2.0-beta.1、候選 v0.2.0-beta.2（測試版）及真實 Release 本文。點擊「前往下載」後 Chrome 新分頁標題為 Release v0.2.0-beta.2 · WeAgileio/ASR-Desktop，URL 為 `https://github.com/WeAgileio/ASR-Desktop/releases/tag/v0.2.0-beta.2`。App 目前版本保持不變，無自動下載或安裝。

此候選的實際 DMG 已於前節從同一 Release 下載並驗證 SHA-256、版本、簽署、arm64 與 runtime；與原 annotated tag／產品 commit 證據相符。`openspec validate add-release-update-notifications --strict` 再次通過。5.3 已完成；5.2 僅剩缺 DMG 的真實上傳驗收，需要獨立測試目標，不能刪除正式 Release 既有資產製造缺包。

## 驗收範圍調整（2026-10-25）

使用者明確指示「缺包不用測試了」，因此取消 5.2 的真實缺 DMG 上傳實測。未建立 WeAgileio/ASR-Desktop-release-validation，也未刪改正式 Release 資產。此項記為使用者免驗，不視為實測成功；缺包邏輯的既有替代 GitHub 回應測試仍保留。5.2 其餘 runner／Xcode、build-only 不發布、資產齊全補包與重跑、校驗一致均已有前述 Actions 證據，按調整後範圍完成。本變更全部 18 項追蹤任務已完成。
