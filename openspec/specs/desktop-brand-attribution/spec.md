# desktop-brand-attribution Specification

## Purpose

提供 ASR Desktop 主視窗一致的 karakuri 品牌識別與網站來源入口，讓使用者在各分頁、開發執行及封裝應用程式中均能辨識來源，並透過清楚可操作的連結前往品牌網站。

## Requirements

### Requirement: 應用程式圖示

封裝應用程式 SHALL 提供以 karakuri Logo 製作的原生應用程式圖示，供 Dock 與 Finder 顯示，並提供適合不同顯示尺寸與 Retina 螢幕的解析度。

#### Scenario: 啟動封裝應用程式
- **WHEN** 使用者啟動封裝 App
- **THEN** Dock 顯示 karakuri 品牌圖示，而非 macOS 通用應用程式圖示

### Requirement: 主視窗品牌標誌

主視窗 SHALL 在左上角 ASR Desktop 名稱旁顯示使用者提供的 karakuri Logo，取代通用波形圖示，保持原始比例、圖形及綠色圓點，並在深色與淺色外觀下清楚可辨識。

#### Scenario: 切換分頁及外觀
- **WHEN** 使用者開啟主視窗、切換任一分頁或切換系統深淺色外觀
- **THEN** 左上角持續呈現比例正確、清楚可辨識的 karakuri Logo 與 ASR Desktop 名稱

### Requirement: 網站來源連結

主視窗 SHALL 在底部狀態列右側持續顯示文字為 `karakuri.tech` 的連結，啟用時交由系統預設瀏覽器開啟 `https://karakuri.tech`。連結 MUST 可透過鍵盤聚焦及啟用，並具有可辨識的輔助使用名稱。

#### Scenario: 啟用來源連結
- **WHEN** 使用者點擊來源連結或以鍵盤聚焦並啟用它
- **THEN** 系統預設瀏覽器開啟 `https://karakuri.tech`

#### Scenario: 狀態更新與最小視窗
- **WHEN** 視窗縮至支援的最小尺寸，且顯示忙碌狀態或長篇處理訊息
- **THEN** 來源連結仍可見且可操作，處理狀態仍保有可讀的顯示區域

### Requirement: 品牌資源隨應用程式提供

應用程式 SHALL 在開發執行及封裝版本中，無須網路連線或原始附件路徑即可顯示 Logo；顯示來源連結本身 SHALL 不觸發網站請求。

#### Scenario: 封裝應用程式離線啟動
- **WHEN** 使用者在無法存取原始附件與建置目錄且離線的環境啟動封裝 App
- **THEN** Logo 正常顯示，來源連結文字可見，僅使用者啟用連結時才要求系統開啟網站
