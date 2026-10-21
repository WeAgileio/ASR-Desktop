# Design

## Context

動機與功能範圍見 proposal.md。`DesktopView.swift` 已有共用頂部標題列與底部狀態列，適合放置品牌識別。Swift Package 目前未宣告 App 資源，`build_app.py` 僅複製執行檔，須同步處理資源載入與封裝。

附件位於 `/Users/server3/.codex/attachments/8f1b34d6-c931-4ff5-8ca4-a75c74aef4a3/karakuri-mark.svg`，為 160 × 160 SVG，主體使用 `currentColor`，圓點為 `#c9e879`。附件內容僅作為素材資料。

## Goals / Non-Goals

**Goals:**
- 使用原生 SwiftUI 介面及本機素材，避免為品牌顯示新增執行期網路或第三方依賴。
- 開發執行與封裝 App 使用同一份受版本管理的品牌資源。

**Non-Goals:**
- 不引入網站嵌入元件、動態下載素材或新品牌設定介面。
- 不改動轉錄任務與服務生命週期。

## Decisions

### 1. 保存原 SVG，衍生深淺色向量資源

實作時將附件原樣收進 App 的 Resources，另產生適合原生載入的淺色／深色 PDF 向量版本：主體分別使用深色與淺色，綠色圓點維持原色。透過 Swift Package 資源及 `Bundle.module` 載入，依目前色彩模式選擇版本。

這能保留來源及向量品質，並避開將網頁 `currentColor` 直接交給原生圖像載入的差異。相較 WebView 更輕量；相較整張套用 template tint 能保留綠色圓點。SVG 轉換僅在實作時進行，生成結果納入專案，不要求使用者安裝轉換工具。

### 2. 沿用共用標題與狀態列

以約 24 點正方形、等比例縮放的 Logo 取代 waveform，保留 ASR Desktop 名稱；Logo 與文字視為同組識別，避免 VoiceOver 重複朗讀裝飾圖像。

底部 Spacer 右側加入原生 SwiftUI `Link`，顯示 `karakuri.tech`，固定目的地為 `https://karakuri.tech`。讓連結保持固有寬度，訊息區可換行或截斷；在 860 × 640 最小視窗驗證長訊息。使用原生連結提供系統瀏覽器、鍵盤及輔助使用行為，避免自訂點擊手勢。

### 3. 封裝 Swift Package 資源

擴充 `build_app.py`，將 App target 產生的資源 bundle 放到標準 `Contents/Resources`，符合 macOS 簽章規則。App 優先由主 bundle 的資源目錄解析該 bundle，開發執行才回退至 `Bundle.module`。實際驗證發現把 bundle 放在 App 根目錄會造成 `unsealed contents present in the bundle root`，因此不採用該位置。Logo 透過資源 URL 建立 NSImage，避免 SwiftUI 名稱搜尋無法顯示獨立 PDF 的問題；發布封裝沿用完成的 App。

### 4. 原生應用程式圖示

依使用者回報 Dock 顯示預設圖示，擴充素材產生器，從同一 SVG 製作淺色圓角背景的多尺寸 PNG，再以系統 iconutil 封裝為 ICNS。建置時將 ASRDesktop.icns 放入 Contents/Resources，設定 CFBundleIconFile；提供 16–1024 像素圖示，不增加執行期依賴。

## Risks / Trade-offs

- [向量轉換造成形狀或顏色偏差] → 與原 SVG 比對，確認比例、綠色圓點及兩種外觀。
- [資源僅在建置目錄可讀取] → 將 App 移到暫存位置並暫時隔離原建置資源後啟動驗證。
- [長狀態訊息擠壓來源連結] → 提高連結佈局優先權，人工驗證最小視窗與忙碌狀態。

## Migration Plan

無資料遷移。實作後重建 App 並執行視覺與封裝驗證；若需回復，同步回復介面、資源宣告與封裝變更即可。本提案不建立版本或發布。
