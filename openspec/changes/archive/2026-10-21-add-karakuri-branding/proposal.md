# Proposal

## Why

ASR Desktop 目前使用通用波形圖示，且沒有呈現 karakuri 的品牌與來源。加入使用者提供的 Logo 及網站連結，讓使用者辨識工具來源並直接前往網站。

## What Changes

- 在主視窗左上角的 ASR Desktop 名稱旁顯示上傳的 karakuri Logo，取代原本的波形圖示。
- 在底部狀態列右側顯示可點擊的 `karakuri.tech`，以系統預設瀏覽器開啟 `https://karakuri.tech`。
- 將品牌素材納入專案資源與應用程式封裝，使開發執行及封裝後均能離線顯示 Logo。
- 依使用者後續回報補上 Dock／Finder 應用程式圖示，使用相同 Logo 製作原生多尺寸圖示。
- 本次範圍不包含產品更名或發版。

## Capabilities

### New Capabilities

- `desktop-brand-attribution`: 桌面主視窗的品牌標誌呈現及可操作的網站來源連結。

### Modified Capabilities

無。

## Impact

- `desktop/Sources/ASRDesktopApp/DesktopView.swift` 的標題區與底部狀態列。
- `desktop/Sources/ASRDesktopApp/Resources/` 的品牌資源與 `desktop/Package.swift` 的資源宣告。
- `desktop/scripts/build_app.py` 的資源封裝流程，以及沿用此產物的發布封裝驗證。
- 不新增第三方執行期依賴；不修改轉錄服務與通訊協定。
