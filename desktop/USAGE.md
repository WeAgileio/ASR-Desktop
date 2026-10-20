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

## 修復

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
