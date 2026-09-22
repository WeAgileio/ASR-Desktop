# 使用 GitHub Actions 建置與 GHCR 部署

GitHub Container Registry（GHCR）是本專案的容器製品庫，鏡像名稱為 `ghcr.io/<owner>/<repository>`，owner 與 repository 會自動轉成小寫。API、Dashboard 共用此鏡像；Redis 使用官方鏡像，FunASR worker 保持在 Mac 原生執行。

## 建置與發布

工作流程：[`container.yml`](../.github/workflows/container.yml)。使用既有 [`Dockerfile`](Dockerfile) 與 service lock，產生 `linux/arm64`（Apple Silicon）及 `linux/amd64` 鏡像。

| 事件 | 行為 |
| --- | --- |
| Pull request | 檢查 Compose、建置並執行服務測試、驗證雙架構建置；不登入或推送 GHCR |
| 預設分支 push | 測試成功後推送 `latest` 與 `sha-<完整 commit SHA>` |
| `v*` tag push | 測試成功後推送同名 tag（例如 `v1.2.3`）與 SHA tag；不更新 `latest` |
| 手動 Run workflow | 選擇預設分支才會執行，發布 `latest` 與 SHA tag |

`latest` 表示預設分支最近建置的版本，不代表正式 release。需要固定部署版本時，使用 workflow summary 顯示的 **digest**；SHA tag 可追溯程式版本，但相同 commit 重建仍可能取得更新的基礎映像。

Workflow 使用 GitHub 自動提供的 `GITHUB_TOKEN`，權限為 `contents: read`、`packages: write`，不用建立 Docker Hub 帳號，也不用把 Google 憑證或部署密碼加入 Actions。Repository／organization 必須允許執行這些 Actions 及寫入 Packages；若已存在同名 package，需在 package 設定授予此 repository Actions 存取權。

這個 workflow 只建置及發布容器，不會操作 Mac、建立 Git tag 或 GitHub Release。專案的版本發布仍遵守既有 Release 流程。

## 第一次部署

先依 [Mac mini 指南](MAC_MINI_GUIDE.md) 完成環境、私有設定與 OAuth。將 workflow 放入 GitHub repository 後，等第一次發布成功，在 Actions summary 複製 `ASR_IMAGE=...@sha256:...`，加到本機私有 `compose.env`。

例如以下是格式示意，請替換成實際值：

```dotenv
ASR_IMAGE=ghcr.io/owner/repository:sha-FULL_COMMIT_SHA
```

首次發布的 package 預設可能是 private；請在 GitHub Packages 確認可見性。Public package 可匿名拉取；private package 請用有該 package 讀取權限的 GitHub 帳號及具 `read:packages` 的 classic PAT 登入。若組織使用 SSO，token 也可能需要 SSO 授權。讓 Docker 互動提示輸入 PAT，勿把 token 寫在命令列或 Compose 檔：

```sh
docker login ghcr.io --username YOUR_GITHUB_USERNAME
```

沿用 Mac mini 指南的 `ASR_APP`、`ASR_CONFIG`，將原本的 Compose 函式改成下方版本。**只使用 `compose.ghcr.yaml`，不必與 `compose.yaml` 合併。**

```sh
asr_compose() {
  docker compose --project-name asr-service \
    --env-file "$ASR_CONFIG/compose.env" \
    -f "$ASR_APP/deployment/compose.ghcr.yaml" "$@"
}

asr_compose config --quiet
asr_compose pull
asr_compose up -d --no-build
asr_compose ps
curl --fail http://127.0.0.1:8090/health
```

Docker 會依主機架構選擇 ARM64 或 AMD64。完成後，依原指南啟動 scanner／worker 並進行兩檔驗收。原生 worker 仍需要對應版本的專案程式及 worker lock，拉取 Docker 鏡像不會更新原生 worker。

## 更新與回退

1. Web 暫停領取，等当前任務結束，停止 scanner／worker，依原指南備份。
2. 將 `ASR_IMAGE` 改成新版本 digest，更新原生程式與依賴至相同版本。
3. 執行 `asr_compose pull`、`asr_compose up -d --no-build`，確認健康。
4. 啟動原生程序，驗收後解除暫停。

回退時指定舊 digest，並恢復相容版本的原生程式與資料備份。資料庫 schema 不一定支援直接降版，不能只換鏡像就視為完成回退。

從本機 build 切換至 GHCR 時，維持原來的 **project name、埠、密碼與資料卷**。兩個 Compose 檔使用相同服務與 volume 名稱；切換不需 `down -v`。如果操作的是既有 `asr-service-validation-2` 測試 stack，請使用該 project name 與原設定，不能直接套用上方 `asr-service` 名稱。

## 本機建置與限制

開發時仍可使用 [`compose.yaml`](compose.yaml) 的 `up --build -d`。部署到 GHCR 時使用 [`compose.ghcr.yaml`](compose.ghcr.yaml)，`ASR_IMAGE` 未設定會直接報錯，避免不小心拉錯版本。

CI 的服務測試在 AMD64 容器執行；ARM64 會完成建置，但 Mac 原生 FunASR／MPS 與 Drive 授權仍需要目標機驗收。`.dockerignore` 僅允許服務程式、Dockerfile 與 service lock 進入 build context，不會將本機音訊、OAuth token 或環境設定包入鏡像。

參考：[GitHub 容器製品庫](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)、[Docker 多架構 Actions](https://docs.docker.com/build/ci/github-actions/multi-platform/)。
