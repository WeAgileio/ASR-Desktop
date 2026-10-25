# ASR Desktop 開發版操作

目前只驗證 Apple M1 Max／macOS 26.6.2。開發版使用直接 helper 啟動，明確顯示「開發模式」；正式簽署、公證、乾淨 Mac 與 macOS 14 驗收尚未完成。模型安裝與日常推論不要求安裝 Python、Homebrew、Redis 或 Docker。

1. 開啟完整 App，在「模型」頁選擇 Nano 或 Paraformer，按「下載／修復」，等到「已就緒」。模型下載也能從 CLI 開始，兩個入口查詢相同狀態。
2. 在「匯入」頁選取或拖入錄好的音訊、影片或資料夾。遞迴掃描需勾選「包含子資料夾」；符號連結不會追蹤。
3. 選擇輸出資料夾、模型、裝置與文字格式，按「預覽批次」檢查有效／無效項目，再提交有效檔案。預設輸出台灣繁體 TXT 與 SRT；JSON 保留原始 transcript。
4. 服務每次啟動後佇列保持暫停。按「恢復佇列」開始逐檔執行；單檔失敗仍繼續其他就緒工作。缺模型的工作顯示等待模型，不占推論槽。
5. 在「任務」頁選擇檔案查看進度、輸出位置與錯誤，使用取消或重試。進度區分實際／估計；無可靠剩餘時間時不顯示 ETA。

關閉視窗或 CLI 不會取消已接受的工作。「暫停佇列」只停止下一檔，當前檔案繼續。「停止背景服務」先暫停領取，等待當前工作完成。CLI `service stop --force` 則走取消與程序群組回收。取消先合作停止，再依 5 秒／5 秒時限發送 TERM／KILL，完全回收前不開始下一檔。突然中斷會保留有效 checkpoint、暫停佇列並標示中斷；明確重試後才能恢復，來源變更時須建立新任務。

輸出名稱加入穩定來源後綴，避免相同 stem 的音訊／影片互相覆蓋。預設不覆寫既有檔案；明確允許覆寫也不能覆寫來源。TXT／SRT／JSON 逐檔提交並保存 checksum ledger，不宣稱多檔同時原子完成。匯出磁碟滿可在釋放空間後重試，重用有效 transcript 與已交付檔案。

## CLI

以下路徑示範安裝位置；開發副本請替換成建置／簽署腳本輸出的 App 路徑。

```sh
ASR="/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop"
"$ASR" diagnose --json
"$ASR" models download paraformer --json
"$ASR" models list --json
"$ASR" submit "$HOME/Movies/meeting.mp4" --output-dir "$HOME/Documents/Transcripts" --model paraformer --device auto --json
"$ASR" queue resume --json
"$ASR" jobs list --json
"$ASR" jobs show batch-EXAMPLE --json
"$ASR" jobs watch batch-EXAMPLE
"$ASR" jobs cancel job-EXAMPLE --json
"$ASR" jobs retry job-EXAMPLE --json
"$ASR" service stop --json
```

`submit --wait` 的成功表示整批完成；不帶 wait 只表示接受提交。遇缺模型、中斷或暫停等待會回傳 3 與 ID，避免無限等待。Ctrl-C 只停止 CLI 觀察，需明確 `jobs cancel` 才取消背景工作。`--request-id` 可保留一個請求 ID，在回應遺失時安全重送相同提交／重試。

在設定頁按「安裝 CLI 連結」，或執行 `cli install`，可在 `~/.local/bin/asr-desktop` 建立連結。同名命令不會覆寫，也不修改 shell 設定。未把該目錄加入 PATH 時，繼續使用 App 內 CLI 的絕對路徑。

```sh
"$ASR" settings show --json
"$ASR" settings set device cpu --json
"$ASR" settings set formats '["txt","srt","json"]' --json
"$ASR" device explain --json
"$ASR" device calibrate "$HOME/Movies/sample.wav" --model paraformer --json
"$ASR" queue resume --json
```

自動模式目前因尚無合格品質基線而使用 CPU。明確 GPU／mps 不被效能資料覆寫；校準由使用者啟動，CPU 與 GPU 使用相同單工槽依序執行，短樣本不授權長內容使用 GPU。詳見 [DEVICE-POLICY.md](DEVICE-POLICY.md)。

## 更新與回退

更新前先用 App 內的 CLI 執行 `queue pause --json`，再執行 `service stop --json`。停止請求被接受不代表已退出；等待 `service status --json` 回傳未連線（退出碼 3），確認目前工作已結束後再備份整個 `~/Library/Application Support/ASR Desktop`。備份應包含資料庫、模型、任務與 attempts；保留原始錄音及輸出目錄。

結束舊 App，將完整的新 App 安裝至原位置，再使用新 App 內的 CLI 執行 `service start --json`、`service status --json`、`models list --json` 和 `jobs list --json`。確認服務 ready、原有任務與模型仍可查詢後，再明確恢復佇列。App 與 CLI 應來自同一安裝包；更新 App 不需要刪除使用者資料目錄或重新下載仍完整的模型。

遇到資料庫版本較新時，優先重新安裝建立該資料庫的 App 版本。若必須回退，先停止所有使用該資料目錄的服務，另存現況，再將更新前的完整資料目錄備份還原並搭配舊 App。不能把舊資料庫直接覆蓋到仍在運作的資料庫，也不能混用新資料庫的 WAL／SHM 檔案。還原會失去備份之後的任務與設定變更。

資料庫升級前會另外產生 `*.before-v<版本>-<時間>.backup`，此檔僅包含資料庫，不包含模型、音訊或輸出。當前 schema 為 1；自動測試覆蓋版本 0 測試資料的升級與備份還原。2026-10-24 已於 macOS 26.6.2 arm64 隔離位置完成 0.1.0 開發版與 0.2.0b2 發布安裝包的更新／回退、備份還原與重連；任務、設定及原有模型檔案保留，舊 runtime 拒絕模擬的較新 schema。兩版 schema 相同，此結果不代表正式簽署、GUI 或 macOS 14 驗收。

## 常見問題

| 狀況 | 可完成的處理方式 |
| --- | --- |
| 模型未就緒、資產遺失 | 在模型頁或 `models verify` 核對，再明確下載／修復 |
| 下載失敗或網路中斷 | 恢復網路後重送下載，保留已驗證資產與安全 partial |
| 空間不足 | 依模型回應的需求釋放空間，或改選輸出資料夾後建立新任務 |
| 既有輸出衝突 | 使用不同目錄，或明確開啟覆寫後重新提交；來源仍受保護 |
| 背景服務未連線 | 設定頁啟動／重新連線，或執行 `service start` |
| 正式建置背景權限被拒 | 依回應到系統設定允許背景項目；不會自動退用開發模式 |
| 內建 runtime 缺失或損壞 | 重新安裝完整且相符版本的 App，再執行診斷 |
| 較新資料庫 schema | 使用建立該資料庫的 App 版本；舊版拒絕寫入，回退需用升級前備份 |

資料與模型保留在 `~/Library/Application Support/ASR Desktop`，可重建音訊在 `~/Library/Caches/ASR Desktop`。開發 helper 私有日誌在 `/private/tmp/asr-desktop-<uid>/development-helper.log`；逐次 worker 日誌位於資料根目錄的 `attempts/<id>/stderr.log`。這些內容可能含來源檔名與辨識診斷，分享前自行檢查。

## 批次與任務管理

任務頁左側可切換全部任務或提交批次，批次依最近提交優先排列。
批次右鍵選單可修改名稱（去除首尾空白後 1–100 個 Unicode 碼位，允許同名）、
重試此批失敗任務或移除此批全部任務紀錄。整批操作不受右側搜尋或分頁限制。

搜尋會涵蓋完整範圍的檔名及批次名稱；文字和狀態條件取交集，多個狀態取聯集。
列表分別顯示範圍數量與符合筆數。勾選任務與點選詳情是獨立操作；同條件換頁保留選取，
切換批次或條件則清除選取。「全選符合結果」包含所有頁面，目標改變後須重新選取。
單筆／選取重試可處理失敗、取消、中斷；「重試此批失敗任務」只重試失敗。
來源遺失或變更會拒絕整次重試。連線失敗後使用「重送原請求以確認結果」，保留原請求 ID。

「移除任務紀錄」確認視窗列出範圍與筆數。原始影音檔與已產生的 TXT、SRT、JSON 成果
都會保留。移除後，無法從原任務查看詳情或重試。此操作不清理快取、不釋放成果空間，
沒有復原功能。執行、取消或回收中的任務須先停止並等待，再重新確認；等待中任務會撤出佇列。

選檔、拖放或變更遞迴設定會自動在背景讀取媒體時長，不必先選輸出目錄。
顯示讀取中或個別失敗原因；未知時長不顯示為零秒。已知正值不足一秒顯示「小於 1 秒」，
其他時長向下取整至秒，以 `m:ss` 或 `h:mm:ss` 顯示。媒體時長不是預估處理時間。
提交仍重新驗證來源，任務之後使用保存的時長，不因重新整理而重讀媒體。

任務列右鍵與詳情皆提供「在 Finder 顯示原始檔」和「在 Finder 顯示成果」。成果入口
選取實際交付的檔案與子資料夾，部分交付也可使用；尚無成果、已遺失或無法開啟時會說明。
若新版 App 提示背景服務缺少能力，請停止舊服務，再以相同版本 App 重新啟動。

## App 版本與更新提醒

主視窗底部及「設定」的「App 版本與更新」顯示相同的本機完整版本，例如 `v0.2.0-beta.2`。它來自 App 安裝包，離線或背景服務未連線時仍可顯示；缺少有效版本資訊時顯示「版本未知」，不猜測是否需要更新。

「啟動時自動檢查更新」預設開啟。每次啟動距離上次自動嘗試滿 24 小時才檢查；常駐期間沒有定時背景輪詢。「檢查更新」可立即手動查詢，但仍遵守 GitHub 的限流等待時間。檢查只讀取公開的 GitHub Release 清單，需要連線至 api.github.com，不傳送錄音、任務、模型路徑或登入 token。

Beta 使用者可收到較新的 beta 或正式版；正式版使用者只收到較新的正式版。目前只認定 macOS 14 以上 Apple Silicon 專用且已上傳完成的 DMG。沒有發布與沒有可用更新會分別顯示；離線、逾時、限流或資料不完整顯示「檢查失敗」，不代表已是最新版。「最後成功檢查」保留上次成功的時間，並非失敗那次的結果。

可用更新會列出版本、通道及文字更新說明。「稍後提醒」關閉本次提示；「略過此版本」會記住此版本並抑制其自動提示，較新版本仍可提示，手動檢查仍能看到略過版本。開關與略過選擇在重新開啟 App 後保留。

「前往下載」僅以預設瀏覽器開啟該版本的 GitHub Release 頁面；若瀏覽器開啟失敗，可在設定重試。App 不會自動下載、安裝、重新啟動或停止轉錄。請自行下載 DMG，並依[更新與回退](#更新與回退)先暫停佇列、等待工作結束、停止服務及完整備份，再安裝新 App；需要降版時使用相應備份還原。開啟下載頁不代表已完成升級。
