# TTS 调试指南 - GitHub Actions 环境

## 当前问题
所有 3 个音色 (Xiaoxiao, Xiaoyi, Xiaohan) 均报 `Invalid voice` 错误。

## 可能原因
1. **edge-tts 7.0.0 语音名称变更** - 新版本可能使用不同的命名格式
2. **GitHub Actions 环境缺少语音数据** - 首次运行需下载，可能被网络阻断
3. **语音名称格式问题** - 可能需要完整名称如 `zh-CN-XiaoxiaoNeural`

## 立即行动：上传代码并查看调试输出

### 1. 更新 Secret
https://github.com/xihai2670-arch/video-pipeline/settings/secrets/actions
```
CF_API_TOKEN = cfut_N1tambs1e9MucLtGIZx6kBg5AwTPLtHbFdEy2uVR280832cc
```

### 2. 网页上传最新代码
本地路径：`C:\Users\Administrator\Documents\deepseek-harness\default-workspace\video-pipeline`

上传全部内容（覆盖现有文件）：
```
.github/
src/
config/
requirements.txt
README.md
.env.example
DEPLOYMENT_CHECKLIST.md
FINAL_DEPLOYMENT_INSTRUCTIONS.md
TTS_DEBUG_GUIDE.md
```

### 3. 运行 Workflow 并查看关键日志

**Actions → Daily Video Pipeline → Run workflow**

重点关注这步输出：
```
Debug edge-tts voices: [...]
```

这会显示 GitHub Actions 环境中**实际可用的所有音色名称**。

---

## 根据调试输出的后续修复

### 情况 A：输出包含类似 `zh-CN-XiaoxiaoNeural` 的名称
修改 `src/generate_assets.py` 的 `fallback_voices`：
```python
self.fallback_voices = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-XiaoyiNeural", 
    "zh-CN-XiaohanNeural",
]
```

### 情况 B：输出为空或只有英文音色
**方案 1：使用 gTTS (Google TTS) 备选**
```python
# 在 requirements.txt 添加
gtts>=2.4.0

# 在 generate_assets.py 添加 gTTS 备选
from gtts import gTTS
def synthesize_gtts(text, output_path):
    tts = gTTS(text=text, lang='zh-cn', slow=False)
    tts.save(str(output_path))
```

**方案 2：使用 pyttsx3 系统 TTS**
```python
# requirements.txt 添加
pyttsx3>=2.90

# 代码中使用
import pyttsx3
engine = pyttsx3.init()
engine.save_to_file(text, str(output_path))
engine.runAndWait()
```

### 情况 C：输出显示其他中文音色可用
直接用输出中显示的名称更新 `fallback_voices`。

---

## 快速修复模板（上传后可直接覆盖）

如果调试显示需要 `Neural` 后缀，使用此文件覆盖 `src/generate_assets.py` 的 TTSGenerator 类：

```python
class TTSGenerator:
    def __init__(self):
        self.voices_config = self._load_voices()
        # 根据调试输出调整：尝试带 Neural 后缀
        self.fallback_voices = [
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-XiaoyiNeural", 
            "zh-CN-XiaohanNeural",
            "zh-CN-Xiaoxiao",
            "zh-CN-Xiaoyi",
            "zh-CN-Xiaohan",
        ]

    async def _synthesize_with_fallback(self, text: str, voice_config: Dict, output_path: Path) -> None:
        primary_name = voice_config.get("name", "zh-CN-Xiaoxiao")
        # 同时尝试带/不带 Neural 的名称
        voice_names = []
        for base in [primary_name] + self.fallback_voices:
            voice_names.append(base)
            if not base.endswith("Neural"):
                voice_names.append(base + "Neural")
        
        # 去重保序
        seen = set()
        voice_names = [v for v in voice_names if not (v in seen or seen.add(v))]
        
        last_error = RuntimeError("未尝试任何音色")
        for voice_name in voice_names:
            try:
                logger.info(f"尝试 TTS 音色: {voice_name}")
                communicate = edge_tts.Communicate(
                    text=text, voice=voice_name,
                    rate=voice_config.get("rate", "+0%"),
                    volume=voice_config.get("volume", "+0%"),
                    pitch=voice_config.get("pitch", "+0Hz")
                )
                await communicate.save(str(output_path))
                logger.info(f"TTS 音色 {voice_name} 合成成功")
                return
            except Exception as e:
                last_error = e
                logger.warning(f"TTS 音色 {voice_name} 失败: {e}")
                continue
        raise RuntimeError(f"所有 TTS 音色均失败: {last_error}")
```

---

## 核心文件清单（确保全部上传）

| 文件 | 关键作用 |
|------|----------|
| `.github/workflows/daily.yml` | **含 Debug edge-tts voices 步骤** |
| `src/generate_assets.py` | TTS 回退逻辑 |
| `config/tts_voices.yaml` | 默认策略 |
| `requirements.txt` | edge-tts>=7.0.0 |

---

**上传 → 运行 → 看 Debug 输出 → 根据输出微调 → 再跑一次** 🎯