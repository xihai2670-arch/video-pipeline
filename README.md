# 视频号中老年短视频自动化流水线 (最终版)

每日自动生成 30 秒竖屏短视频（9:16 MP4）+ 3:4 带标题封面图，面向视频号中老年受众（50-75 岁），内容以温情故事为主。

## 🎯 核心特性

| 功能 | 实现方式 | 容错机制 |
|------|----------|----------|
| **文案生成** | SiliconFlow Qwen2.5-72B | - |
| **分镜配图** | SiliconFlow (Kolors/SDXL/FLUX) + Cloudflare 备选 | 多模型回退 + 响应格式兼容 + 403/400 自动跳过 |
| **图生视频** | HF LTX-Video → 本地 ffmpeg 合成兜底 | HF 失败自动本地合成 |
| **旁白配音** | Edge TTS 本地离线合成 | - |
| **视频合成** | ffmpeg 拼接 + 字幕烧录 + BGM 混音 | - |
| **封面生成** | 配图 + 文字叠加 → 3:4 (1080×1440) | - |
| **合规风控** | 敏感词库 + 版权启发式 + 平台规则检查 | 不通过拦截 |
| **调度部署** | GitHub Actions 每日 06:00 定时运行 | 产物上传 Artifact |

## 🏗️ 架构概览

```
GitHub Actions (每日 06:00 CST)
        │
        ▼
┌─────────────────────────────────────────┐
│  Python 流水线 (main.py)                 │
├─────────────────────────────────────────┤
│  1. generate_script.py  → script.json   │  SiliconFlow Qwen2.5-72B
│  2. generate_assets.py  → 图/视频/音频  │  SiliconFlow/Kolors → Cloudflare → 本地 ffmpeg
│  3. compose_video.py    → final_video.mp4│  ffmpeg 拼接+字幕+BGM
│  4. compliance.py       → 合规报告      │  敏感词/版权/平台规则
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
- **API 凭据**（配置为 GitHub Secrets）：

| Secret 名称 | 来源 | 用途 |
|------------|------|------|
| `SILICONFLOW_API_KEY` | [SiliconFlow](https://cloud.siliconflow.cn/) | 文生图 + 文本生成 (国内直连) |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) | 备选文本生成 |
| `CF_ACCOUNT_ID` | Cloudflare Dashboard 右侧 | 备选文生图 |
| `CF_API_TOKEN` | Cloudflare API Tokens → Workers AI Read | 备选文生图 |
| `HF_TOKEN` | [Hugging Face](https://huggingface.co/settings/tokens) | 图生视频 |

## 🚀 快速部署

### 1. Fork / 创建仓库
```bash
git clone <your-repo>
cd <your-repo>
# 复制本项目所有文件到仓库根目录
```

### 2. 配置 GitHub Secrets
仓库 → Settings → Secrets and variables → Actions → New repository secret
添加上述 5 个 Secret。

### 3. 启用 Actions
仓库 → Actions → 启用 "Daily Video Pipeline" 工作流。

### 4. 手动触发测试
Actions 页面 → "Daily Video Pipeline" → Run workflow → Run workflow。

### 5. 查看产物
运行完成后，Artifacts 会有 `video-output-<run_id>.zip`，解压得到：
```
output/20241128_001/
├── final_video.mp4      # 最终视频 (9:16, 30s, MP4)
├── cover_with_title.jpg # 封面图 (3:4, 1080×1440)
├── script.json          # 完整脚本
├── publish.json         # 发布文案
├── summary.json         # 运行汇总
└── images/videos/audio/ # 中间素材
```

## 🔧 关键容错机制

### 图片生成（多层回退）
```
SiliconFlow (Kolors → SDXL → SDXL-Turbo → FLUX.1-dev)
    ↓ 全部失败
Cloudflare (FLUX-Schnell → SDXL, 400重试+参数自适应)
    ↓ 全部失败
抛出异常 → 流水线终止
```

### 视频生成（双重兜底）
```
HF LTX-Video (免费配额)
    ↓ 失败/不可用
本地 ffmpeg 合成：单图 → 缩放动画 + 淡入淡出 → 5秒视频
```

### 响应格式兼容
- SiliconFlow: `b64_json` 优先，`url` 下载兜底
- Cloudflare: 标准 base64 字段

### 尺寸自适应
- Cloudflare: 强制正方形，对齐 64 倍数，400 时简化参数重试

## ⚙️ 配置说明

### 视频规格（`compose_video.py` 可修改）
- 分辨率：1080×1920 (9:16)
- 帧率：30 fps
- 编码：H.264 (libx264), CRF 23, yuv420p
- 音频：AAC 128kbps, 44.1kHz
- 时长：固定 30 秒

### 音色选择（`config/tts_voices.yaml`）
| 类别 | 推荐音色 | 适用场景 |
|------|----------|----------|
| 温情亲情 | `zh-CN-Xiaoxiao` (女) | 奶奶讲故事感 |
| 生活智慧 | `zh-CN-Yunxi` (男) | 磁性大叔讲述 |
| 时代记忆 | `zh-CN-Yunyang` (男) | 沉稳厚重感 |

### 合规敏感词（`config/sensitive_words.txt`）
包含政治、色情、赌博、诈骗、医疗承诺、金融诱导、违规营销等 500+ 词。
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
| 季度 | 评估 SiliconFlow/Cloudflare/HF 配额消耗，决定是否接入付费/自建 GPU |

## 🛠️ 扩展指南

### 接入内容安全 API（图片/视频合规）
修改 `compliance.py` 中的 `check_image_compliance` / `check_video_compliance`：
```python
# 示例：阿里云内容安全
from aliyunsdkcore.client import AcsClient
from aliyunsdkgreen.request.v20180509 import ImageSyncScanRequest
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
A: HF 免费层高峰期排队久，已内置本地 ffmpeg 兜底。可在 `daily.yml` 调大 `timeout-minutes`。

**Q: 合规误拦截？**
A: 检查 `sensitive_words.txt` 是否有过度匹配，调整正则或加白名单逻辑。

**Q: 想要 60 秒视频？**
A: 修改 `prompt_templates.yaml` 中场景数为 12，`compose_video.py` 中 `-t "60"`，但 HF 配额消耗翻倍。

**Q: 本地跑不通 ffmpeg？**
A: 确保 `ffmpeg -version` 正常输出。Windows 建议用 winget 安装。

**Q: 封面文字位置不对？**
A: 在 `compose_video.py` 的 `generate_cover_with_text` 中调整 `y=` 参数。

## 📝 更新日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2024-11-28 | 初版：完整流水线、合规检查、GH Actions 部署、多模型回退、本地视频兜底 |

## 📄 许可证

MIT License - 可商用、可修改、可分发。

## ⚠️ 免责声明

- 本工具生成内容仅供参考，**发布前必须人工复核**合规性
- 使用免费 API 受限于服务方配额与 SLA，不保证 100% 可用
- 视频号平台规则随时变更，敏感词库需持续维护
- 生成内容版权归使用者所有，但需自行承担发布法律责任

---

**开始你的日更之旅 🎬** —— 推送代码，明早 06:00 就能在 Artifacts 里看到第一条视频！