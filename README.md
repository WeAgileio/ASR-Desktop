# ASR SRT

Apple Silicon Mac 上的本機影片轉 SRT 生成器。支援使用者選擇 Fun-ASR-Nano-2512 或 Paraformer，並將中文為主、英文為輔的辨識結果轉為台灣繁體 SRT。影片、音訊、模型與 transcript 都留在本機。

## Requirements

- Apple Silicon Mac
- Python 3.9+（建議使用 Python 3.11）
- [Homebrew](https://brew.sh/)
- FFmpeg
- 首次安裝模型需要網路，之後可離線執行

Fun-ASR-Nano 模型權重約 2.15 GB，實際快取還會包含 VAD 與相關檔案。Paraformer 較小且通常在 CPU 處理長影片更快。

## Installation

```bash
brew install ffmpeg python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

確認環境：

```bash
asr-srt --diagnose
```

## Usage

使用預設 Fun-ASR-Nano、自動選擇 MPS/CPU，將 SRT 寫在影片旁：

```bash
asr-srt "/path/to/interview.mp4"
```

選擇 Paraformer：

```bash
asr-srt video.mp4 --model paraformer
```

使用熱詞：

```bash
asr-srt video.mp4 \
  --hotword FunASR \
  --hotword "OpenAI,ModelScope,DaVinci Resolve"
```

強制 CPU、自訂輸出並覆寫已有 SRT：

```bash
asr-srt video.mp4 \
  --model paraformer \
  --device cpu \
  --output subtitles/video.zh-TW.srt \
  --overwrite
```

調整切句：

```bash
asr-srt video.mp4 \
  --max-units 18 \
  --max-duration 5 \
  --min-duration 0.8 \
  --silence-gap 0.6
```

預設會輸出台灣繁體。如果要保留模型原文：

```bash
asr-srt video.mp4 --no-traditional
```

## Progress display

預設 `--progress auto` 會在互動終端使用可原地更新的 Rich 畫面；輸出被導向檔案、pipe 或 CI 時，自動改用不含 ANSI 控制碼的純文字事件。也可以明確指定：

```bash
asr-srt video.mp4 --progress rich
asr-srt video.mp4 --progress plain
asr-srt video.mp4 --progress off
```

- 音訊擷取百分比來自 FFmpeg 已處理的媒體時間，屬於實測值。
- FunASR 搭配內建 VAD 時，callback 可能只代表內部 batch；工具不會把它假裝成整部影片百分比。第一次執行會顯示 spinner 與已用時間。
- 同一模型版本、device/backend 與 runtime 累積至少兩個 30 秒以上的成功樣本後，ASR 可顯示標記為 `estimated`／`~` 的百分比與 ETA。估算在真正完成前不會到達 100%。
- 效能樣本存放在 `<cache-dir>/performance.json`，不屬於 transcript cache key；刪除或損毀只會失去 ETA，不會使辨識失敗。
- transcript cache 命中時，音訊擷取、模型準備與 ASR 會明確顯示為 `skipped`。

若要把執行紀錄保存到檔案，建議使用 `--progress plain`。不要強制 `--progress rich` 後再重定向，否則檔案會包含終端控制碼。

## Model choice

| Model | Best for | Trade-off |
|---|---|---|
| `fun-asr-nano` | 中英混合、專業詞彙、口音與上下文 | 模型較大；Mac MPS 相容性需依實機驗證 |
| `paraformer` | 中文長影片、較低記憶體、成熟時間戳 | 英文術語可能更依賴熱詞 |

模型與 device 是兩個獨立選擇。`--device auto` 優先使用 MPS；若出現已知的 MPS 相容性錯誤，會明確顯示訊息後以 CPU 重試一次。`--device mps` 是強制模式，失敗時不會靜默切換 CPU。

## Output and cache

- 預設輸出：`video.mp4` → `video.srt`
- 已存在的 SRT 不會被覆寫，除非使用 `--overwrite`
- 原始影片永不修改
- ModelScope 模型通常位於 `~/.cache/modelscope`；工具會優先使用其中完整的本機權重，不會因工作 cache 不同而重新下載
- transcript、中間音訊與進度效能樣本預設放在 `~/Library/Caches/asr-srt`
- 修改字幕字數、持續時間或繁簡設定時，可重用 transcript，不需重跑 ASR
- 修改模型、熱詞或辨識設定會建立新快取
- 可以 `--no-cache` 強制重新辨識

## Troubleshooting

### FFmpeg or ffprobe is missing

```bash
brew install ffmpeg
```

### PyTorch or FunASR is missing

確認已啟用 virtual environment，然後執行：

```bash
python -m pip install -e .
```

### MPS failure

先讓 `--device auto` 進行 CPU 退路。若要排除 MPS 差異：

```bash
asr-srt video.mp4 --device cpu
```

### Existing SRT blocks output

改用新的 `--output` 路徑，或在確認可替換後加上 `--overwrite`。

## Tests

不載入模型的快速測試：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

真實 Apple Silicon 模型評測請參考 `evaluation/manifest.example.json` 與 `evaluation/RESULTS.md`，不要將私人影片或完整 transcript 提交到專案。
