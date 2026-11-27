"""素材生成模块 - 图片、视频、音频并发生成"""
import os
import json
import logging
import asyncio
import base64
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from utils import ROOT_DIR, CONFIG_DIR, retry_with_backoff, compute_hash
from compliance import check_image_compliance, check_video_compliance

logger = logging.getLogger(__name__)

try:
    import requests
    from huggingface_hub import InferenceClient
    import edge_tts
except ImportError as e:
    logger.warning(f"依赖缺失: {e}")

@dataclass
class AssetPaths:
    """单条视频的素材路径集合"""
    run_dir: Path
    script: Dict[str, Any]

    @property
    def images_dir(self) -> Path:
        p = self.run_dir / "images"
        p.mkdir(exist_ok=True)
        return p

    @property
    def videos_dir(self) -> Path:
        p = self.run_dir / "videos"
        p.mkdir(exist_ok=True)
        return p

    @property
    def audio_dir(self) -> Path:
        p = self.run_dir / "audio"
        p.mkdir(exist_ok=True)
        return p

    def image_path(self, scene_idx: int) -> Path:
        return self.images_dir / f"scene_{scene_idx:02d}.png"

    def video_path(self, scene_idx: int) -> Path:
        return self.videos_dir / f"scene_{scene_idx:02d}.mp4"

    def audio_path(self, scene_idx: int) -> Path:
        return self.audio_dir / f"scene_{scene_idx:02d}.mp3"

    def cover_path(self) -> Path:
        return self.run_dir / "cover.jpg"

    def final_video_path(self) -> Path:
        return self.run_dir / "final_video.mp4"

    def bgm_path(self) -> Path:
        return self.run_dir / "bgm.mp3"


class ImageGenerator:
    """Cloudflare Workers AI 文生图"""

    def __init__(self, account_id: str, api_token: str):
        self.account_id = account_id
        self.api_token = api_token
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        # FLUX.1-schnell 模型
        self.model = "@cf/black-forest-labs/flux-1-schnell"

    @retry_with_backoff(max_attempts=3, base_delay=3.0)
    def generate(self, prompt: str, width: int = 1024, height: int = 1820) -> bytes:
        """生成图片，返回二进制数据"""
        url = f"{self.base_url}/{self.model}"
        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_inference_steps": 4,  # schnell 只需 4 步
            "guidance_scale": 3.5
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        if not result.get("success"):
            raise RuntimeError(f"Cloudflare AI 返回错误: {result}")
        # 返回 base64 解码后的图片
        image_b64 = result["result"]["image"]
        return base64.b64decode(image_b64)


class VideoGenerator:
    """Hugging Face Inference API 图生视频"""

    def __init__(self, hf_token: str):
        self.client = InferenceClient(token=hf_token, timeout=300)
        # 模型优先级
        self.models = [
            "Lightricks/LTX-Video",           # 最快、最省配额
            "THUDM/CogVideoX-2b",             # 备选
            "WanVideo/Wan2.1-I2V-14B-480P",   # 高质量备选
        ]

    @retry_with_backoff(max_attempts=2, base_delay=10.0)
    def generate_i2v(self, image_bytes: bytes, prompt: str, model_idx: int = 0) -> bytes:
        """图生视频，返回 MP4 二进制"""
        if model_idx >= len(self.models):
            raise RuntimeError("所有视频模型均尝试失败")

        model = self.models[model_idx]
        logger.info(f"使用模型生成视频: {model}")

        try:
            # HF Inference API 的 text_to_video / image_to_video
            # 注意：不同模型参数不同，这里用通用方式
            video_bytes = self.client.image_to_video(
                image=image_bytes,
                prompt=prompt,
                model=model,
                # LTX-Video 参数
                num_frames=25,      # 5秒 * 5fps (LTX 通常 5-8fps)
                fps=5,
                width=512,
                height=512,
                num_inference_steps=25,
                guidance_scale=6.0
            )
            return video_bytes
        except Exception as e:
            logger.warning(f"模型 {model} 失败: {e}, 尝试下一个")
            return self.generate_i2v(image_bytes, prompt, model_idx + 1)


class TTSGenerator:
    """Edge TTS 本地语音合成"""

    def __init__(self):
        self.voices_config = self._load_voices()

    def _load_voices(self) -> Dict:
        import yaml
        with open(CONFIG_DIR / "tts_voices.yaml", 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def pick_voice(self, topic_category: str = "default") -> Dict:
        """根据话题类别选择音色"""
        strategy = self.voices_config.get("default_strategy", {})
        voice_name = strategy.get(topic_category, strategy.get("default", "zh-CN-Yunxi"))
        # 查找完整配置
        for category in ["warm_male", "warm_female", "dialect"]:
            for v in self.voices_config["voices"][category]:
                if v["name"] == voice_name:
                    return v
        # 兜底
        return self.voices_config["voices"]["warm_male"][0]

    async def synthesize(self, text: str, voice_config: Dict, output_path: Path) -> None:
        """合成语音到文件"""
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_config["name"],
            rate=voice_config.get("rate", "+0%"),
            volume=voice_config.get("volume", "+0%"),
            pitch=voice_config.get("pitch", "+0Hz")
        )
        await communicate.save(str(output_path))

    def synthesize_sync(self, text: str, voice_config: Dict, output_path: Path) -> None:
        """同步包装"""
        asyncio.run(self.synthesize(text, voice_config, output_path))


class AssetGenerator:
    """素材生成总调度"""

    def __init__(self, cf_account_id: str, cf_api_token: str, hf_token: str):
        self.image_gen = ImageGenerator(cf_account_id, cf_api_token)
        self.video_gen = VideoGenerator(hf_token)
        self.tts_gen = TTSGenerator()

    def generate_all(self, script: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
        """生成所有素材，返回路径映射"""
        assets = AssetPaths(run_dir, script)
        scenes = script["scenes"]

        # 1. 并发生成配图
        logger.info("生成分镜配图...")
        image_paths = []
        for i, scene in enumerate(scenes):
            img_path = assets.image_path(i + 1)
            if not img_path.exists():
                img_bytes = self.image_gen.generate(scene["image_prompt"])
                img_path.write_bytes(img_bytes)
                # 合规检查
                check_result = check_image_compliance(img_path)
                if not check_result["passed"]:
                    logger.warning(f"场景 {i+1} 配图合规不通过: {check_result['issues']}")
            image_paths.append(str(img_path))

        # 2. 并发生成视频片段（串行避免配额耗尽）
        logger.info("生成视频片段...")
        video_paths = []
        for i, scene in enumerate(scenes):
            vid_path = assets.video_path(i + 1)
            if not vid_path.exists():
                img_bytes = Path(image_paths[i]).read_bytes()
                vid_bytes = self.video_gen.generate_i2v(img_bytes, scene["video_prompt"])
                vid_path.write_bytes(vid_bytes)
                # 合规检查
                check_result = check_video_compliance(vid_path)
                if not check_result["passed"]:
                    logger.warning(f"场景 {i+1} 视频合规不通过: {check_result['issues']}")
            video_paths.append(str(vid_path))

        # 3. 生成旁白音频
        logger.info("生成旁白音频...")
        voice = self.tts_gen.pick_voice(self._infer_category(script))
        audio_paths = []
        for i, scene in enumerate(scenes):
            aud_path = assets.audio_path(i + 1)
            if not aud_path.exists():
                self.tts_gen.synthesize_sync(scene["narration"], voice, aud_path)
            audio_paths.append(str(aud_path))

        # 4. 生成封面图
        logger.info("生成封面图...")
        cover_path = assets.cover_path()
        if not cover_path.exists():
            cover_prompt = self._build_cover_prompt(script)
            cover_bytes = self.image_gen.generate(cover_prompt, width=1080, height=1440)
            cover_path.write_bytes(cover_bytes)

        # 5. 准备 BGM（占位：使用免费素材库或静音）
        bgm_path = assets.bgm_path()
        if not bgm_path.exists():
            self._prepare_bgm(script["bgm_mood"], bgm_path)

        return {
            "images": image_paths,
            "videos": video_paths,
            "audios": audio_paths,
            "cover": str(cover_path),
            "bgm": str(bgm_path),
            "voice_used": voice["name"],
            "final_video": str(assets.final_video_path())
        }

    def _infer_category(self, script: Dict[str, Any]) -> str:
        """从标题/标签推断话题类别"""
        text = script.get("title", "") + " " + " ".join(script.get("tags", []))
        if any(kw in text for kw in ["亲", "爱", "情", "孙", "子", "女", "夫", "妻", "伴"]):
            return "亲情温情"
        if any(kw in text for kw in ["智慧", "学", "技", "艺", "医", "工", "教", "书"]):
            return "生活智慧"
        return "时代记忆"

    def _build_cover_prompt(self, script: Dict[str, Any]) -> str:
        """构建封面提示词"""
        templates = __import__('utils').load_yaml(CONFIG_DIR / "prompt_templates.yaml")
        # 简化：直接拼接关键元素
        return f"{script['cover_title']}, {script['cover_subtitle']}, {script['title']}, warm nostalgic cinematic lighting, 3:4 aspect ratio, space for text overlay"

    def _prepare_bgm(self, mood: str, output_path: Path) -> None:
        """准备背景音乐（占位：生成静音文件，实际应接入免费 BGM 库）"""
        # 生成 30 秒静音 MP3 作为占位
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "30", "-c:a", "libmp3lame", "-b:a", "128k", str(output_path)
        ], check=False, capture_output=True)
        logger.info("BGM 占位文件已生成（静音），建议替换为版权清晰的音乐")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    # 简单测试
    cf_id = os.getenv("CF_ACCOUNT_ID")
    cf_token = os.getenv("CF_API_TOKEN")
    hf_token = os.getenv("HF_TOKEN")

    if not all([cf_id, cf_token, hf_token]):
        print("请设置环境变量")
        exit(1)

    # 测试配图
    img_gen = ImageGenerator(cf_id, cf_token)
    img = img_gen.generate("elderly couple drinking tea in garden, warm sunset, cinematic")
    Path("test_image.png").write_bytes(img)
    print("测试图片已生成: test_image.png")