---
description: Codex 專案相關規定
globs:
  - "**/*"
alwaysApply: true
---

# Git 與發版規則

## Git 提交流程規則

在這個專案中，**只要需要你協助執行任何會影響遠端狀態的 git 操作（包含 `commit`、`tag`、以及 `push`/`push --tags` 推送）時，操作順序必須嚴格遵守：**

1. `git pull`：先從遠端拉取最新變更，處理衝突後再繼續。
2. `git commit`：使用符合本檔案規則的 Commits 規範建立提交。
3. `git push`：最後才把本地提交推送到遠端。

- 若使用者已經手動完成其中部分步驟（例如先自己 pull），你可以跳過已完成的步驟，但 **絕對不得在未 pull 的情況下直接進行 `commit → push` 或 `tag → push tag`**。
- 在實際執行任何 git 指令前，**必須先用自然語言向使用者說明你打算執行的步驟與指令，並等待使用者確認後再執行**。

## Commits 規範

### 1. Commit 訊息格式

```text
<type>[可選 scope]: <description>

[可選 body]

[可選 footer(s)]
```

### 2. 類型（type）

- **feat**: 新功能
- **fix**: 錯誤修復
- **docs**: 文件相關修改
- **style**: 格式調整（不影響程式邏輯，如空白、分號等）
- **refactor**: 重構（非修 bug、非加功能）
- **perf**: 效能優化
- **test**: 測試新增或修正
- **build**: 建置系統或相依套件變更
- **ci**: CI/CD 流程變更
- **chore**: 雜項或維護性工作（不影響產品功能）

### 3. Scope（範圍）

- scope 為 **可選**。
- 若有幫助，請使用 **簡短名詞** 描述影響範圍。

```text
feat(auth): 新增 SSO 登入
fix(api): 處理空 payload
docs(readme): 更新安裝步驟
```

### 4. Description（描述）

- 預設使用 **英文小寫**（除非團隊規範改為中文）。
- 描述需 **簡潔且具體**。
- **不要加句號結尾**。
- 使用 **祈使句（imperative）**。

### 5. Breaking Changes（破壞性變更）

若為破壞性修改，請在 type 後加上 `!`：

```text
feat(api)!: 移除 v1 session 端點
refactor(core)!: 調整 plugin 生命週期鉤子
```

必要時在 footer 加上：

```text
BREAKING CHANGE: 說明變更內容、影響對象、遷移方式
```

### 6. Body（內文）

僅在「有價值」時補充，內容可以包含：

- 為什麼需要這個變更
- 重要實作細節
- 取捨或副作用

### 7. Footer（附註）

```text
BREAKING CHANGE: 說明破壞性變更內容
Refs: #123
Closes: #456
```

### 8. 選擇規則（Selection Rules）

- 若同時包含功能與修復，優先拆成多個 commit。
- 若只能寫一個，選主要意圖。
- 不要捏造 diff 中不存在的變更。
- 若使用者只要 commit message，不要多餘說明。

### 9. 輸出規則（Output Rules）

1. 第一行必須符合 Conventional Commit 格式。
2. 僅在必要時補 body / footer。
3. 預設輸出為純文字（除非另有要求）。

### 10. 良好範例

```text
feat(auth): 新增 Google OAuth 登入
fix(upload): 避免重複提交檔案
docs(readme): 釐清本地開發環境設定
refactor(api): 簡化錯誤對應邏輯
perf(search): 快取標籤彙總結果
test(payment): 新增 webhook 重試測試覆蓋
chore(deps): 升級 vite 至 6
ci(github): 新增 release 流程
feat(api)!: 移除舊版 token 端點

BREAKING CHANGE: 客戶端須從 /v1/token 遷移至 /v2/token
```

### 11. 不良範例

```text
新增了登入功能（用了過去式，且無 type）
修 bug（描述過於籠統）
更新一些東西（語意不清）
feat: 新增了新功能（description 勿用大寫開頭、勿用過去式）
```

## Release 規則

當你要協助建立新版本（例如：打 tag、建立 GitHub Release、或在討論中明確提到「release / 發版 / 上線」）時，必須同時確保：

- `README.md` 中有對應這次版本的 **Release Notes** 區塊或條目，至少包含本次版本的簡短功能說明；若有破壞性修改需特別標註，且不要描述技術性調整。
- 若 `README.md` 尚未有 Release 區塊，先在底部新增「Release Notes」章節，再加入本次版本說明。
- 建立或推送 tag、建立 GitHub Release 前，先確認或補齊上述 Release Notes。
- 產生 release 描述或 changelog 時，優先復用或同步 `README.md` 的 Release Notes，避免內容不一致。
- 使用者明確說「發版」時，預設同時完成 **Git 發版 + GitHub Release**，除非使用者明確表示不要 GitHub Release。
- 預設執行順序：
  1. 整理版本內容，必要時更新 `README.md` 版本紀錄與 `package.json` 版本號。
  2. Git 發版：`git pull` → `commit` → 建立並推送與 `package.json` 一致的 **annotated tag** → `push` / `push --tags`。
  3. GitHub Release：標籤存在於遠端後，以 `gh release create <tag>` 建立 Release；若本機無 `gh` 或未登入，需向使用者說明並協助完成，不可略過此步。
- 若缺少版本號、tag 命名規則等必要資訊，先向使用者確認；資訊齊全則完整執行到 Git 與 GitHub Release 發布完成。
