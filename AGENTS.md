# 專案 Agent 工作規則

本檔案適用於本專案及其所有子目錄。使用者當次明確指示優先於本檔案的預設規則。

所有工作亦須遵守 [`.codex/rules/command-confirmation.md`](.codex/rules/command-confirmation.md) 中定義的 Git 提交、Conventional Commits 與 Release 規則。

## 1. 實作前先釐清

- 根據資料與證據判斷，不一昧順從；清楚區分已確認的事實、推論與尚未驗證的事項。
- 實作前說明會影響結果的假設與取捨，不隱藏疑問。
- 若有多種合理解讀且會明顯影響結果，先列出差異並確認；若不影響結果，可說明合理假設後繼續。
- 必要資訊缺失、需求互相衝突或無法安全判斷時，先指出問題並詢問。
- 若有更簡單的解法，主動提出；簡單任務不必套用冗長流程。

## 2. 保持簡單與精準修改

- 只實作需求所需的最少內容，不加入未要求的功能、設定或預留擴充。
- 不為單次使用的程式碼建立不必要的抽象，也不為不可能發生的情境增加錯誤處理。
- 遵循既有程式風格，只修改與本次需求直接相關的程式碼、註解和格式。
- 不順便重構無關區域；發現既有死碼或其他問題時，可提出但不擅自刪改。
- 移除因本次修改而變得未使用的 import、變數或函式。
- 每一處修改都應能對應到使用者需求；若方案過度複雜，先簡化。

## 3. 以可驗證的結果完成工作

- 開始前定義可觀察的成功條件，不以「看起來能用」作為完成標準。
- 多步驟任務提供簡短計畫，說明各步驟與驗證方式。
- 新增驗證邏輯時，確認合法與不合法輸入的預期行為。
- 修復錯誤時，先重現問題；適合時加入能防止問題再次發生的測試。
- 重構時，確認修改前後的相關測試與行為一致。
- 依變更風險選擇必要的測試與檢查；單純文件或低風險修改不必新增無意義的測試。
- 持續修正直到成功條件通過；無法驗證時，明確說明原因及未驗證範圍，不宣稱已通過。

## 4. Git 操作

### 執行前確認

- 執行任何 Git 指令前，先以自然語言說明目的、操作順序、實際指令及目標分支／遠端，等待使用者確認後再執行。
- 此要求包含 `git status`、`git diff` 等唯讀指令。
- 一次確認可涵蓋已明確列出的整段流程，不必對同一流程的每條指令重複詢問。若需新增未涵蓋的操作或改變目標，先說明並重新確認。
- 使用者僅要求 commit message 或討論發版時，不代表授權執行 Git 操作或發布。

### 提交與推送順序

`commit` 與 `tag` 本身只改變本地狀態，`push` 才會更新遠端；本專案仍要求提交或建立版本標籤前先整合遠端變更。

1. **Pull**：先從正確的遠端與分支拉取最新變更，處理衝突後再繼續。保留使用者尚未提交的修改。
2. **Commit**：依下方 Conventional Commits 規範建立提交。
3. **Push**：最後將本地提交推送至事先確認的遠端分支。

- 若使用者已完成其中部分步驟，可在確認完成狀態後跳過，不重複操作。
- 不得在未 pull 的情況下直接執行 `commit → push` 或 `tag → push tag`。
- 若沒有可拉取的遠端／分支，或拉取失敗，先說明並確認處理方式，不把 fetch 或失敗的 pull 當成已完成整合。
- 單純推送分支不等於合併至主分支，也不等於發版；依使用者授權範圍執行。

## 5. Commit 訊息規範

### 格式

使用 Conventional Commits：

```text
<type>[可選 scope][可選 !]: <description>

[可選 body]

[可選 footer(s)]
```

### 類型與範圍

| type | 用途 |
|---|---|
| feat | 新功能 |
| fix | 錯誤修復 |
| docs | 文件修改 |
| style | 不影響程式邏輯的格式調整 |
| refactor | 非新增功能、非修復錯誤的重構 |
| perf | 效能優化 |
| test | 測試新增或修正 |
| build | 建置系統或相依套件變更 |
| ci | CI/CD 流程變更 |
| chore | 其他不影響產品功能的維護工作 |

scope 可省略；有助理解時，用簡短名詞表示影響範圍，例如 `auth`、`api`、`readme`。

### 描述、內文與附註

- description 預設使用英文、以小寫動詞開頭，採祈使句，簡潔具體，不以句號結尾；專案規範或使用者指定中文時改用中文。
- 專有名詞保留正確大小寫，例如 Google、OAuth、SSO。
- body 僅在有價值時補充原因、重要實作細節、取捨或副作用。
- footer 可使用 `Refs: #123`、`Closes: #456`；只引用實際相關的事項。
- 破壞性變更使用 `type(scope)!:`，沒有 scope 時使用 `type!:`；必要時加上 `BREAKING CHANGE:`，說明影響與遷移方式。

```text
feat(auth): add Google OAuth sign-in
fix(upload): prevent duplicate submissions
docs(readme): clarify local setup steps
refactor(api): simplify error mapping
perf(search): cache tag summaries
test(payment): cover webhook retries
chore(deps): upgrade vite to version 6
ci(github): add release workflow
```

破壞性變更範例：

```text
feat(api)!: remove the legacy token endpoint

BREAKING CHANGE: migrate clients from /v1/token to /v2/token
```

### 選擇與輸出

- 同時包含功能與修復時，優先拆成多個有明確意圖的 commit；只能提交一次時，type 依主要意圖選擇。
- 訊息必須符合實際 diff，不捏造變更，避免「修 bug」「更新一些東西」等模糊描述。
- 使用者只要求 commit message 時，只輸出訊息本身，不加解釋；預設純文字，不加 Markdown 程式碼區塊。
- 第一行必須符合上述格式；body／footer 僅在必要時補充。

## 6. 發版規則

### 範圍與授權

- 使用者明確要求「發版」時，預設包含 **Git 版本提交與標籤推送，以及 GitHub Release 建立**。除非使用者當次明確排除，不能只完成其中一部分。
- 僅討論 release／發版／上線不等於授權發布；準備版本內容或說明時，仍遵守下方 Release Notes 規則。
- 發版同樣遵守第 4 節的 Git 執行前確認。必要資訊齊全且整段流程已確認後，持續完成已授權流程，不反覆要求相同確認。
- 版本號、目標分支或 tag 規則不明時，先確認，不自行猜測。

### README Release Notes

- 在建立或推送 tag、建立 GitHub Release 前，先確認 `README.md` 有該版本的 Release Notes。
- 若沒有 Release Notes 章節，在 README 底部新增，再加入該版本條目。
- 條目以使用者可感知的功能新增與問題修復為主，不列純技術調整；破壞性變更須明確標示影響及必要的遷移方式。
- Release 描述與 changelog 優先沿用或同步至 README 的版本條目，保持一致。

### 執行順序

1. 整理版本內容，依上述更新日誌規則更新 `src/content/releases.json`，同步 README Release Notes 並完成驗證；必要時更新專案的版本來源，保持 `package.json`／`package-lock.json` 版本一致。
2. `git pull`，整合遠端變更並處理衝突。
3. `git commit`，提交該版本內容；若內容已提交，不製造無意義的空提交。
4. 建立 **annotated tag**，例如 `git tag -a v1.2.0 -m "v1.2.0"`，標籤須對應正確的版本提交。
5. 推送目標分支與本次版本標籤，優先明確指定單一 tag，避免 `push --tags` 意外發布其他本地標籤。
6. 確認標籤已存在遠端後，執行 `gh release create <tag>` 建立 GitHub Release；標題可使用版本號，內文依 README 該版本條目整理。
7. 核對遠端分支、標籤與 GitHub Release，回報版本及 Release 連結；未完成的步驟須明確說明。

若本機缺少 `gh` 或尚未登入，說明阻礙，協助安裝／登入後再執行，或交由使用者在網頁建立；在完成前不得聲稱已完整發版，也不可默默略過 GitHub Release。

## 7. 來源

實作行為準則整理自使用者提供的 Karpathy Guidelines（原文標示 MIT 授權），其引用來源為 [Andrej Karpathy 對 LLM 程式開發常見問題的觀察](https://x.com/karpathy/status/2015883857489522876)。Git 與發版規則依使用者提供的專案要求整理。
