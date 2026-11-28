# 部署清单 - 视频号中老年短视频自动化流水线

## 📋 当前状态总结

| 组件 | 状态 | 说明 |
|------|------|------|
| **代码** | ✅ 完成 | 所有容错机制已实现 |
| **Git 仓库** | ⚠️ 本地已提交 | 需推送到 GitHub（网络问题） |
| **GitHub Secrets** | ⚠️ 部分配置 | 需确认 CF_API_TOKEN 已更新 |
| **GitHub Actions** | ⚠️ 待触发 | 代码推送后需手动重跑 |

---

## ✅ 已完成的核心功能

### 1. 文案生成
- **SiliconFlow Qwen2.5-72B** - 国内直连，稳定生成结构化脚本
- 合规检查：敏感词、版权、平台规则三重拦截

### 2. 图片生成 - 多层回退
```
SiliconFlow (Kolors → SDXL → SDXL-Turbo → FLUX.1-dev)
    ↓ 全部 403/400/401/429
Cloudflare (FLUX-Schnell → SDXL, 400重试+正方形尺寸+简化参数)
```

### 3. 视频生成 - 双重兜底
```
HF LTX-Video (免费配额)
    ↓ 失败/不可用 (StopIteration 等)
本地 ffmpeg 合成：单图 → 缩放动画 + 淡入淡出 → 5秒视频
```

### 4. 完整容错机制
- **响应格式兼容**：SiliconFlow b64_json / url 双支持
- **Cloudflare 400 处理**：强制正方形尺寸(64对齐) + 简化参数重试
- **视频生成兜底**：HF 失败自动本地 ffmpeg 合成（缩放动画+淡入淡出）
- **任意错误自动回退**：任何错误自动尝试下一个模型/服务

---

## 🚀 剩余部署步骤（3步，5分钟）

### 步骤 1：更新 GitHub Secret
访问：https://github.com/xihai2670-arch/video-pipeline/settings/secrets/actions

| Secret 名称 | 值 |
|-------------|-----|
| `CF_API_TOKEN` | `cfut_N1tambs1e9MucLtGIZx6kBg5AwTPLtHbFdEy2uVR280832cc` |

### 步骤 2：网页上传代码（必须）
1. 打开：https://github.com/xihai2670-arch/video-pipeline
2. **Add file** → **Upload files**
3. 选择本地 `video-pipeline` 文件夹**所有内容**拖入：
   - `.github/` (含 workflows/daily.yml)
   - `src/` (含 generate_assets.py 最终版)
   - `config/`
   - `requirements.txt`
   - `README.md`
   - `.env.example`
4. **Commit changes**

> ⚠️ 注意：`.git` 文件夹不要上传

### 步骤 3：触发 Actions
1. 进入 **Actions** 标签页
2. 点击 **Daily Video Pipeline**
3. 点击 **Run workflow** → **Run workflow**

---

## 🎯 预期成功日志

```
Debug secrets: SILICONFLOW_API_KEY length: 52
生成脚本: 使用 SiliconFlow (Qwen2.5-72B) → 脚本合规通过
生成素材: 尝试 SiliconFlow 模型: Kwai-Kolors/Kolors → 生成成功 (url 下载)
生成视频片段: 使用本地 ffmpeg 合成视频... (或 HF 成功)
合成视频: final_video.mp4 (9:16, 30s)
生成封面: cover_with_title.jpg (3:4)
```

---

## 🔧 故障排查速查表

| 症状 | 排查方向 |
|------|----------|
| `SILICONFLOW_API_KEY length: 0` | Secret 名字/值/位置错误 |
| `403 Model disabled` | SiliconFlow 多模型回退会自动处理 |
| `400 Bad Request` | Cloudflare 会自动重试简化参数 |
| `StopIteration` 视频失败 | 自动触发本地 ffmpeg 合成 |
| `所有视频模型均尝试失败` | 检查 HF_TOKEN 是否有效/有配额 |

---

## 📊 监控指标

每日运行产出 `output/YYYYMMDD_XXX/summary.json`：
```json
{
  "status": "success",
  "duration_seconds": 180,
  "steps": {
    "script": {"status": "success", "topic": "..."},
    "assets": {"status": "success", "images": 6, "videos": 6, "voice": "zh-CN-Xiaoxiao"},
    "compose": {"status": "success", "final_video": "...", "size_mb": 15.2},
    "final_compliance": {"passed": true}
  }
}
```

---

## 📅 定期维护

| 频率 | 动作 |
|------|------|
| 每周 | 检查 `used_topics.json`，补充 `config/topics.txt` |
| 每月 | 更新 `config/sensitive_words.txt` |
| 季度 | 评估 API 配额，决定是否付费/自建 GPU |

---

## 📞 最后确认

部署完成后，请在 Actions 页面观察第一次运行：
1. ✅ Debug secrets 显示 Key 长度 > 0
2. ✅ 生成脚本显示 "使用 SiliconFlow" 并合规通过
3. ✅ 生成素材显示 "Kwai-Kolors/Kolors 生成成功"
4. ✅ 视频片段显示 "使用本地 ffmpeg 合成" 或 HF 成功
5. ✅ 最终产出 `final_video.mp4` + `cover_with_title.jpg`

**完成上述步骤，你的每日自动化视频流水线就正式上线了！** 🎬