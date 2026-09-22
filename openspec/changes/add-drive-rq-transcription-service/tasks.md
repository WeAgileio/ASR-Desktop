## 1. Runtime 與相容性驗證

- [x] 1.1 建立隔離服務 runtime 並固定 Python、RQ、Redis client、Google client 與 API 依賴；驗證乾淨安裝成功且既有 CLI 環境不變。
- [x] 1.2 用小型真實音檔在目前可用 Mac 驗證 RQ SpawnWorker 使用 MPS、任務結束釋放模型與長呼叫期間持續心跳；記錄版本、實際硬體、耗時、memory pressure 和 swap，必要時驗證監督程序／IPC 備案；目標 M4／16GB 驗收保留於 7.4。
- [x] 1.3 分離 API／worker 套件入口及依賴，驗證 API 啟動不匯入 PyTorch 或載入模型。

## 2. 持久化與控制 API

- [x] 2.1 建立 SQLite migration，涵蓋批次、關聯、任務、attempt、artifact、outbox、scan lease 與服務控制；驗證唯一鍵、外鍵和重複 migration。
- [x] 2.2 實作批次提交與查詢、worker／scanner 狀態回報及控制 API；驗證設定快照、URL／ID 輸入與非法狀態轉換。
- [x] 2.3 實作管理登入、worker token 驗證和瀏覽器 mutation 防護；驗證未授權請求、敏感資訊遮蔽及任意任務函式拒絕。
- [x] 2.4 實作短交易、busy timeout 與一致性備份；驗證並發回報不遺失資料，備份可還原任務與 outbox。

## 3. Drive 掃描

- [x] 3.1 實作 host-only 服務帳號載入、來源／目的地預檢及 shared-drive API 參數；以 mocks 驗證 My Drive 來源、唯讀目的地和缺少 shared-drive ID 的阻擋行为。
- [x] 3.2 實作遞迴與分頁、visited set、捷徑／垃圾桶／輸出樹排除及範圍驗證；用多層 fixtures 驗證完整枚舉與部分失敗不發布。
- [x] 3.3 實作來源版本／設定／目的地身份和穩定自然排序；驗證重掃、改名、同名異 ID、內容更新和跨批次去重。
- [x] 3.4 實作原生掃描程序、掃描 lease、手動重掃和可選週期掃描；驗證轉錄中仍能掃描且重啟不重複建立任務。

## 4. RQ 派送與單工恢復

- [x] 4.1 實作 SQLite outbox dispatcher、JSON payload、穩定 RQ ID；注入 Redis 斷線與 enqueue 回應遺失，驗證補送不遺漏且不重複有效執行。
- [x] 4.2 實作 execution token、事件序號、心跳與同機執行鎖；測試重複 worker、重複消息及舊 attempt 回報被拒絕。
- [x] 4.3 串接原生 workflow callback、source download 驗證與原子本機 manifest；驗證下載中來源更新被攔截以及估計進度標記保留。
- [x] 4.4 設定明確 timeout、RQ Retry／scheduler、錯誤分類與人工重試；驗證暫時錯誤退避、權限 blocked、壞檔 failed 和後續任務可繼續。
- [x] 4.5 實作 restart／queue-loss reconciliation 和離線發布閘門；驗證 Redis 資料遺失、API 中斷、worker 被終止時不與舊程序重疊，恢復沿用相容 checkpoint。
- [x] 4.6 實作持久暫停／恢復領取；驗證當前任務完成、下一個不啟動，且重啟仍維持暫停。

## 5. 結果生成與 Drive 交付

- [x] 5.1 建立共用 TXT 匯出與 completion metadata，沿用現有 SRT；驗證繁體轉換、內容保留、未校訂標記及時間碼契約。
- [x] 5.2 實作來源／版本資料夾映射、預配置 Drive ID 和 artifact manifest；測試同名來源及 create 成功但回應遺失仍只留下同一結果物件。
- [x] 5.3 實作 checksum 驗證、補傳、completion 最後寫入及最終狀態回報；驗證部分上傳、權限撤銷、最終回報遺失時不重跑辨識或重複交付。
- [x] 5.4 實作容量 admission 與可配置保留期；驗證容量不足阻擋下載且清理不刪除未交付成果。

## 6. Web 與部署

- [x] 6.1 建立提交、批次／檔案列表和任務詳情頁；以瀏覽器驗證深層來源、進度、錯誤、重試、暫停及結果連結，失聯和估計值顯示明確。
- [x] 6.2 建立 Compose 與 SQLite／Redis 持久 volume、AOF、loopback 綁定；驗證容器替換保留紀錄，API 使用 service name、Mac 使用本機映射埠。
- [x] 6.3 整合受限 RQ Dashboard，限制繞過業務 API 的 mutation 入口；驗證未授權存取與管理操作不能造成狀態漂移。
- [x] 6.4 提供 LaunchAgent、worker／scanner 設定與絕對路徑範本；驗證 Docker 延後啟動時重連，文件明確標示登入、睡眠與 MPS 前提。
- [x] 6.5 補操作文件，包含憑證儲存、設定、備份、恢復、更新及回退；依文件在隔離資料目錄完成一次還原演練。

## 7. 整合驗收

- [x] 7.1 執行既有單元測試及新增服務整合測試；驗證 CLI、既有 cache／SRT／progress 契約沒有回歸。
- [x] 7.2 使用兩個測試媒體完成提交、掃描、串行辨識、Drive 回傳、Web 結果展示；先取得明確可寫測試目的地，只測選定檔案，不批量處理既有來源。
- [x] 7.3 執行 worker 強制中斷、Redis 重啟、API 回應遺失與上傳失敗的端到端故障演練；交付紀錄證明單工、無重複結果與續跑成立。
- [ ] 7.4 在 M4／16GB 測試代表性長音訊與兩筆排隊任務，記錄資源和超時設定；確認 MPS、心跳、長內容恢復與 Docker 共存，不以其他機器數據代替。

## 8. 使用者 OAuth（因 My Drive 目的地補充）

- [x] 8.1 加入桌面 OAuth loopback／PKCE 登入與本機 600 權限 token 儲存，驗證授權失敗不洩漏 token、不覆寫既有有效資料。
- [x] 8.2 增加明確的 OAuth／服務帳號模式、模式相依目的地預檢與過期授權錯誤處理；保留服務帳號的 shared-drive 限制並更新操作文件。
- [x] 8.3 完成使用者首次 Google 授權，驗證所提供 My Drive 目的地可存取；真實媒體交付仍由 7.2 追蹤。
