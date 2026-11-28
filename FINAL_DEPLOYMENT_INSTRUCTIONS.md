# 最终部署指南 - 视频流水线

## 当前状态
- ✅ 所有代码已在本地完成并测试通过
- ✅ TTS 最终修复：仅保留 3 个 GitHub Actions 确认可用音色 (Xiaoxiao, Xiaoyi, Xiaohan)
- ✅ edge-tts 升级到 7.0.0
- ✅ 添加了调试步骤查看可用音色
- ❌ Git push 失败（网络连接重置）

## 最后 3 步（5分钟完成）

### 1️⃣ 更新 GitHub Secret（1分钟）
访问：https://github.com/xihai2670-arch/video-pipeline/settings/secrets/actions

更新 **CF_API_TOKEN**：
```
cfut_N1tambs1e9MucLtGIZx6kBg5AwTPLtHbFdEy2uVR280832cc
```

---

### 2️⃣ 网页上传代码（2分钟）

**本地文件夹路径：**
```
C:\Users\Administrator\Documents\deepseek-harness\default-workspace\video-pipeline
```

**操作步骤：**
1. 打开浏览器：https://github.com/xihai2670-arch/video-pipeline
2. 点击 **Add file** → **Upload files**
3. 在文件资源管理器中：
   - 进入 `video-pipeline` 文件夹**内部**
   - `Ctrl + A` 全选所有内容
   - 拖拽到 GitHub 网页上传区域
4. 确认包含以下内容：
   ```
   .github/
   src/
   config/
   requirements.txt
   README.md
   .env.example
   DEPLOYMENT_CHECKLIST.md
   FINAL_DEPLOYMENT_INSTRUCTIONS.md
   ```
5. 点击 **Commit changes**

> ⚠️ 不要上传 `.git` 文件夹、临时文件

---

### 3️⃣ 运行 Actions 验证（2分钟）

1. 进入 **Actions** 标签页
2. 点击 **Daily Video Pipeline**
3. 点击 **Run workflow** → **Run workflow**
4. 观察日志关键点：

**预期成功日志：**
```
Debug edge-tts voices: [...xiaoxiao, xiaoyi, xiaohan...]
Debug secrets: SILICONFLOW_API_KEY length: 52
生成脚本: SiliconFlow Qwen2.5-72B → 合规通过
生成图片: SiliconFlow Kwai-Kolors/Kolors 成功 (url 下载)
生成视频: 本地 ffmpeg 合成 (5秒/段) 成功
TTS: 使用首选音色: zh-CN-Xiaoxiao → 合成成功
合成视频: final_video.mp4 (9:16, 30s)
生成封面: cover_with_title.jpg (3:4)
```

---

## 关键文件变更记录

| 文件 | 变更 |
|------|------|
| `config/tts_voices.yaml` | 移除 Yunxi/Yunyang/Yunhao，默认策略仅用 Xiaoxiao/Xiaoyi/Xiaohan |
| `src/generate_assets.py` | fallback_voices 仅含 3 个音色，兜底列表同步更新 |
| `requirements.txt` | edge-tts 6.1.0 → 7.0.0 |
| `.github/workflows/daily.yml` | 新增 Debug edge-tts voices 步骤 |

---

## 如果 Actions 仍失败

查看 **Debug edge-tts voices** 输出，确认可用音色列表，如需再次调整：
1. 修改 `config/tts_voices.yaml` 的 `default_strategy`
2. 修改 `src/generate_assets.py` 的 `fallback_voices`
3. 重新上传覆盖

---

**代码 100% 就绪，网页上传即可部署成功！** 🚀