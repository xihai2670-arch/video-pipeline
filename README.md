# 视频号中老年短视频自动化流水线

每日自动生成 30 秒竖屏短视频（9:16 MP4）+ 3:4 带标题封面图，面向视频号中老年受众（50-75 岁），内容以温情故事为主。

## 🎯 核心特性

| 功能 | 实现方式 |
|------|----------|
| **文案生成** | Gemini 1.5 Flash → 结构化分镜脚本（6 场景 × 5s = 30s） |
| **分镜配图** | Cloudflare Workers AI (FLUX.1-schnell) → 9:16 高清配图 |
| **图生视频** | Hugging Face Inference API (LTX-Video 优先) → 5s 动态片段 |
| **旁白配音** | Edge TTS 本地合成 → 中老年风音色（云希/晓晓等） |
| **视频合成** | ffmpeg → 拼接 + 字幕烧录 + BGM 混音 + 规范化编码 |
| **封面生成** | 配图 + 文字叠加 → 3:4 (1080×1440) 高点击率封面 |
| **合规风控** | 敏感词库 + 版权启发式 + 平台规则检查，不通过拦截 |
| **调度部署** | GitHub Actions 每日 06:00 定时运行，产物上传 Artifact |

## 🏗️ 架构概览

```
GitHub Actions (每日 06:00 CST)
        │
        ▼
┌─────────────────────────────────────────┐
│  Python 流水线 (main.py)                 │
├─────────────────────────────────────────┤
│  1. generate_script.py  → script.json   │
│  2. generate_assets.py  → 图/视频/音频  │
│  3. compose_video.py    → final_video.mp4│
│  4. compliance.py       → 合规报告      │
└─────────────────────────────────────────┘
        │
        ▼
   Artifact 上传 (保留 30 天)
        │
        ▼
   手工下载 → 视频号发布
```

## 📋 环境要求

- **GitHub 仓库**（公开或私有，Actions 免费额度足够）
- **Python 3.11+**（Actions 自动安装）
- **ffmpeg**（Actions 自动安装 `sudo apt-get install ffmpeg`）
- **API 凭据**（配置为 GitHub Secrets）：

| Secret 名称 | 来源 | 用途 |
|------------|------|------|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) | 文案生成 |
| `CF_ACCOUNT_ID` | Cloudflare Dashboard → 右侧 Account ID | 文生图 |
| `CF_API_TOKEN` | Cloudflare API Tokens → Workers AI Read | 文生图 |
| `HF_TOKEN` | [Hugging Face Settings](https://huggingface.co/settings/tokens) | 图生视频 |

## 🚀 快速部署

### 1. Fork / 创建仓库
```bash
git clone <your-repo>
cd <your-repo>
# 复制本项目所有文件到仓库根目录
```

### 2. 配置 GitHub Secrets
仓库 → Settings → Secrets and variables → Actions → New repository secret
添加上述 4 个 Secret。

### 3. 启用 Actions
仓库 → Actions → 启用 "Daily Video Pipeline" 工作流。

### 4. 手动触发测试
Actions 页面 → "Daily Video Pipeline" → Run workflow → Run workflow。

### 5. 查看产物
运行完成后，Artifacts 会有 `video-output-<run_id>.zip`，解压得到：
```
output/20241126_001/
├── script.json          # 完整脚本
├── publish.json         # 发布文案
├── summary.json         # 运行汇总
├── final_video.mp4      # 最终视频 (9:16, 30s, MP4)
├── cover_with_title.jpg # 封面图 (3:4, 带标题)
├── images/              # 6 张分镜配图
├── videos/              # 6 个视频片段
├── audio/               # 6 段旁白
└── compliance_report.json
```

## 🔧 本地开发/调试

```bash
# 1. 克隆并进入
cd video-pipeline

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 ffmpeg (Windows)
winget install Gyan.FFmpeg
# macOS: brew install ffmpeg
# Linux: sudo apt install ffmpeg

# 5. 配置 .env 文件
cp .env.example .env  # 填入你的 4 个 API Key

# 6. 单步测试
python -m src.generate_script      # 仅生成脚本
python -m src.generate_assets      # 仅生成素材 (需先有 script.json)
python -m src.compose_video        # 仅合成视频
python -m src.main                 # 完整流水线
```

## 📁 目录结构

```
video-pipeline/
├── .github/workflows/daily.yml    # GitHub Actions 定时任务
├── src/
│   ├── main.py                    # 主入口
│   ├── generate_script.py         # 文案生成 (Gemini)
│   ├── generate_assets.py         # 素材生成 (CF/HF/Edge-TTS)
│   ├── compose_video.py           # 视频合成 (ffmpeg)
│   ├── compliance.py              # 合规检查
│   └── utils.py                   # 通用工具
├── config/
│   ├── sensitive_words.txt        # 敏感词库 (200+ 词)
│   ├── prompt_templates.yaml      # 所有 Prompt 模板
│   └── tts_voices.yaml            # Edge TTS 音色配置
├── requirements.txt
├── .env.example                   # 环境变量模板
└── README.md
```

## ⚙️ 关键配置说明

### 视频规格（可在 `compose_video.py` 修改）
- 分辨率：1080×1920 (9:16)
- 帧率：30 fps
- 编码：H.264 (libx264), CRF 23, yuv420p
- 音频：AAC 128kbps, 44.1kHz
- 时长：固定 30 秒

### 成本控制（HF 免费层）
- 单条视频 ≈ 6 次图生视频调用
- HF 免费层月配额约 300-500 次 → **月产 30-50 条**
- 建议：起步 30 秒/条，跑通后评估是否升级付费

### 音色选择（`tts_voices.yaml`）
| 类别 | 推荐音色 | 适用场景 |
|------|----------|----------|
| 温情亲情 | `zh-CN-Xiaoxiao` (女) | 奶奶讲故事感 |
| 生活智慧 | `zh-CN-Yunxi` (男) | 磁性大叔讲述 |
| 时代记忆 | `zh-CN-Yunyang` (男) | 沉稳厚重感 |

### 合规敏感词（`sensitive_words.txt`）
包含政治、色情、赌博、诈骗、医疗承诺、金融诱导、违规营销等 200+ 词。
**新增敏感词**：直接追加到文件，无需改代码。

## 📊 监控与维护

### GitHub Actions 监控
- 每日运行日志在 Actions 页面查看
- 失败会发送邮件通知（需在 Settings → Notifications 开启）
- `summary.json` 包含每步耗时、成功/失败、合规结果

### 定期维护
| 频率 | 动作 |
|------|------|
| 每周 | 检查 `used_topics.json` 去重效果，补充新选题到 `config/topics.txt` |
| 每月 | 更新 `sensitive_words.txt`（参考平台最新违规案例） |
| 季度 | 评估 HF 配额消耗，决定是否接入付费/自建 GPU |

## 🛠️ 扩展指南

### 接入内容安全 API（图片/视频合规）
修改 `compliance.py` 中的 `check_image_compliance` / `check_video_compliance`：
```python
# 示例：阿里云内容安全
from aliyunsdkcore.client import AcsClient
from aliyunsdkgreen.request.v20180509 import ImageSyncScanRequest

def check_image_compliance(image_path):
    client = AcsClient(access_key_id, access_secret, region)
    request = ImageSyncScanRequest()
    request.set_accept_format('JSON')
    # ... 上传图片并检测
    return {"passed": True, "issues": []}
```

### 接入网盘自动上传
在 `main.py` 的 `run()` 结束处添加：
```python
# 示例：阿里云盘
from aliyundrive import AliyunDrive
drive = AliyunDrive(refresh_token)
drive.upload(run_dir / "final_video.mp4", "视频号素材/")
```

### 替换视频模型
在 `generate_assets.py` 的 `VideoGenerator.models` 列表调整优先级，或添加新模型 ID。

### 增加 BGM 库
在 `AssetGenerator._prepare_bgm()` 中接入免费音乐 API（如 YouTube Audio Library、DOVA-SYNDROME 等）。

## ❓ 常见问题

**Q: 视频生成超时/失败？**
A: HF 免费层高峰期排队久，Actions 设置了 60 分钟超时。可在 `daily.yml` 调大 `timeout-minutes`，或在 `generate_assets.py` 增加重试间隔。

**Q: 合规误拦截？**
A: 检查 `sensitive_words.txt` 是否有过度匹配，调整正则或加白名单逻辑。

**Q: 想要 60 秒视频？**
A: 修改 `prompt_templates.yaml` 中场景数为 12，`compose_video.py` 中 `-t "60"`，但 HF 配额消耗翻倍。

**Q: 本地跑不通 ffmpeg？**
A: 确保 `ffmpeg -version` 正常输出。Windows 建议用 winget 安装，避免路径问题。

**Q: 封面文字位置不对？**
A: 在 `compose_video.py` 的 `generate_cover_with_text` 中调整 `y=` 参数。

## 📝 更新日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2024-11-26 | 初版：完整流水线、合规检查、GH Actions 部署 |

## 📄 许可证

MIT License - 可商用、可修改、可分发。

## ⚠️ 免责声明

- 本工具生成内容仅供参考，**发布前必须人工复核**合规性
- 使用免费 API 受限于服务方配额与 SLA，不保证 100% 可用
- 视频号平台规则随时变更，敏感词库需持续维护
- 生成内容版权归使用者所有，但需自行承担发布法律责任

---

**开始你的日更之旅 🎬** —— 推送代码，明早 06:00 就能在 Artifacts 里看到第一条视频！