# Tasks

## 1. 共用模型登錄

- [x] 1.1 擴充模型配置及共用登錄讀取，集中模型名稱、引擎、必要資產、裝置能力與需求說明；以有效配置、未知引擎及既有模型相容性測試驗證。
- [x] 1.2 將核心 JobConfig、CLI、desktop intake 與 offline loader 改用登錄及能力驗證；測試新增相容模型不需模型名稱分支，並驗證不支援裝置或熱詞會在接受工作前被拒絕。
- [x] 1.3 固定工作使用的引擎與推論配置識別，納入快取相容性判斷並支援既有工作格式；測試登錄更新後舊工作不改用新配置且不誤用快取，更新 desktop/MODELS.md 說明登錄格式與限制。

## 2. 權重與推論引擎

- [x] 2.1 核對兩個官方模型的實際權重來源及必要檔案，產生固定 revision、大小與 SHA-256 的完整資產清單；以 catalog 驗證、準備及重新校驗確認下載量與資產完整性，維護生成腳本可重現兩個新模型且保留舊模型。
- [x] 2.2 新增 Taiwan Tongues 的 faster-whisper CPU Adapter 與 session，接上本地快照及真實時間戳正規化；以介面測試驗證 CPU 參數、時間界限、空白結果與缺失時間戳的處理。
- [x] 2.3 新增 Breeze 的 Transformers Whisper CPU Adapter 與 session，載入本地權重、processor 及解碼設定；以介面測試驗證時間戳轉換、長音訊解碼、無外連載入及錯誤診斷。
- [x] 2.4 將兩個 Adapter 接入既有長音檔分段、checkpoint 與字幕輸出；以跨段時間偏移、模型重用與字幕生成整合測試驗證，並於 desktop/MODELS.md 說明語言及熱詞限制。

## 3. 模型頁與執行環境

- [x] 3.1 SwiftUI 模型選單改由清單動態產生，依能力提供裝置選項；模型頁顯示平台、CPU、GPU、記憶體估算與未知最低需求、真實下載量及準備空間，以 native build 與畫面檢查驗證。
- [x] 3.2 更新 Python 相依套件、desktop runtime lock 與 PyInstaller 的模型模組及原生函式庫收集；以依賴一致性檢查和 frozen runtime 載入兩種新增引擎驗證，更新建置及使用文件。

## 4. 整合驗收

- [x] 4.1 使用兩個真實模型各以 CPU 完成短錄音轉錄及 SRT，準備完成後封鎖外連重跑；記錄環境、輸出與記憶體觀測範圍於 runtime-validation.md，不設定效能門檻且不將短片測試宣稱為最低硬體保證。
- [x] 4.2 執行既有 Python 回歸測試、native build 與 frozen App 模型選擇、下載、離線轉錄及需求頁驗收，記錄結果與任何未通過項目；未實際完成的驗收不得勾選。
