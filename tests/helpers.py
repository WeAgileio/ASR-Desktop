from pathlib import Path

from asr_srt.domain import TextUnit, Transcript, TranscriptMetadata


def transcript(cache_key="key", device="cpu"):
    return Transcript(
        full_text="你好 FunASR！这是测试。",
        duration_ms=4000,
        language="中文",
        units=(
            TextUnit("你", 0, 300), TextUnit("好", 300, 600),
            TextUnit("FunASR", 650, 1200), TextUnit("！", 1200, 1250),
            TextUnit("这", 1800, 2100), TextUnit("是", 2100, 2400),
            TextUnit("测", 2400, 2700), TextUnit("试", 2700, 3000),
            TextUnit("。", 3000, 3050),
        ),
        metadata=TranscriptMetadata(
            "test-model", "r1", device, ("FunASR",), 0.1, cache_key
        ),
    )

