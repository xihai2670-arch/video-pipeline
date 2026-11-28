"""素材生成模块 - 图片、视频、音频并发生成 (最终版：全容错+视频生成兜底)"""
import os
import json
import logging
import asyncio
import base64
import hashlib
import subprocess
import tempfile
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
    from openai import OpenAI
except ImportError as e:
    logger.warning(f"依赖缺失: {e}")

@dataclass
class AssetPaths:
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


class SiliconFlowImageGenerator:
    """SiliconFlow 文生图 - 多模型回退 + 响应格式兼容 + 403自动跳过"""

    def __init__(self, api_key: str):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.siliconflow.cn/v1",
            timeout=60.0,
            max_retries=0
        )
        # 按可用性排序：Kolors(中文友好) > SDXL > SDXL-Turbo > FLUX.1-dev
        self.models = [
            "Kwai-Kolors/Kolors",
            "stabilityai/stable-diffusion-xl-base-1.0",
            "stabilityai/sdxl-turbo",
            "black-forest-labs/FLUX.1-dev",
        ]

    def generate(self, prompt: str, width: int = 1024, height: int = 1820) -> bytes:
        last_error = None
        
        for model in self.models:
            try:
                logger.info(f"尝试 SiliconFlow 模型: {model}")
                response = self.client.images.generate(
                    model=model,
                    prompt=prompt,
                    size=f"{width}x{height}",
                    response_format="b64_json",
                    n=1
                )
                
                image_b64 = None
                image_url = None
                
                if response.data and len(response.data) > 0:
                    data = response.data[0]
                    
                    if hasattr(data, 'b64_json') and data.b64_json:
                        image_b64 = data.b64_json
                    elif hasattr(data, 'url') and data.url:
                        image_url = data.url
                
                if image_b64:
                    logger.info(f"SiliconFlow 模型 {model} 生成成功 (b64_json)")
                    return base64.b64decode(image_b64)
                elif image_url:
                    logger.info(f"SiliconFlow 模型 {model} 生成成功 (url 下载)")
                    import requests
                    resp = requests.get(image_url, timeout=30)
                    resp.raise_for_status()
                    return resp.content
                else:
                    logger.warning(f"SiliconFlow 模型 {model} 响应无图片数据: {response}")
                    continue
                    
            except Exception as e:
                error_str = str(e)
                logger.warning(f"SiliconFlow 模型 {model} 失败: {e}")
                if "403" in error_str or "Model disabled" in error_str or "disabled" in error_str.lower() \
                   or "400" in error_str or "401" in error_str or "429" in error_str:
                    continue
                continue
                
        raise RuntimeError(f"所有 SiliconFlow 模型均失败，最后错误: {last_error}")


class CloudflareImageGenerator:
    """Cloudflare Workers AI 文生图 - 多模型 + 参数自适应 + 400重试"""

    def __init__(self, account_id: str, api_token: str):
        self.account_id = account_id
        self.api_token = api_token
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self.models = [
            "@cf/black-forest-labs/flux-1-schnell",
            "@cf/stabilityai/stable-diffusion-xl-base-1.0",
        ]

    def generate(self, prompt: str, width: int = 1024, height: int = 1820) -> bytes:
        last_error = None
        
        for model in self.models:
            try:
                logger.info(f"尝试 Cloudflare 模型: {model}")
                url = f"{self.base_url}/{model}"
                
                cf_size = min(max(width, height), 1024)
                cf_size = max(cf_size, 512)
                cf_size = (cf_size // 64) * 64
                
                payload = {
                    "prompt": prompt,
                    "width": cf_size,
                    "height": cf_size,
                    "num_inference_steps": 4,
                    "guidance_scale": 3.5
                }
                
                response = requests.post(url, headers=self.headers, json=payload, timeout=60)
                
                if response.status_code == 400:
                    logger.warning(f"Cloudflare 400: {response.text[:200]}")
                    simple_payload = {"prompt": prompt}
                    response = requests.post(url, headers=self.headers, json=simple_payload, timeout=60)
                
                response.raise_for_status()
                result = response.json()
                
                if not result.get("success"):
                    raise RuntimeError(f"Cloudflare AI 返回错误: {result}")
                
                image_b64 = result.get("result", {}).get("image")
                if not image_b64:
                    raise RuntimeError(f"Cloudflare 无图片数据: {result}")
                
                logger.info(f"Cloudflare 模型 {model} 生成成功")
                return base64.b64decode(image_b64)
                
            except Exception as e:
                logger.warning(f"Cloudflare 模型 {model} 失败: {e}")
                continue
                
        raise RuntimeError("所有 Cloudflare 模型均失败")


class ImageGenerator:
    """图片生成器：SiliconFlow 优先，Cloudflare 备选"""

    def __init__(self, siliconflow_key: str = None, cf_account_id: str = None, cf_api_token: str = None):
        self.generators = []
        
        if siliconflow_key:
            self.generators.append(("SiliconFlow", SiliconFlowImageGenerator(siliconflow_key)))
        
        if cf_account_id and cf_api_token:
            self.generators.append(("Cloudflare", CloudflareImageGenerator(cf_account_id, cf_api_token)))
        
        if not self.generators:
            raise RuntimeError("至少需要配置 SiliconFlow 或 Cloudflare 其中一个")

    def generate(self, prompt: str, width: int = 1024, height: int = 1820) -> bytes:
        last_error = None
        for name, gen in self.generators:
            try:
                logger.info(f"尝试 {name} 生成图片...")
                return gen.generate(prompt, width, height)
            except Exception as e:
                last_error = e
                logger.warning(f"{name} 生成失败: {e}")
                continue
        raise last_error or RuntimeError("所有图片生成器均失败")


class VideoGenerator:
    """视频生成：HF Inference API 优先，失败则本地 ffmpeg 合成图片序列动画"""

    def __init__(self, hf_token: str):
        self.client = InferenceClient(token=hf_token, timeout=300)
        # 只保留免费可用的模型
        self.models = [
            "Lightricks/LTX-Video",
        ]

    @retry_with_backoff(max_attempts=2, base_delay=10.0)
    def generate_i2v(self, image_bytes: bytes, prompt: str, model_idx: int = 0) -> bytes:
        if model_idx >= len(self.models):
            logger.warning("HF 视频模型均不可用，将使用本地 ffmpeg 合成图片序列动画")
            return None  # 返回 None 触发本地合成兜底

        model = self.models[model_idx]
        logger.info(f"尝试 HF 视频模型: {model}")

        try:
            video_bytes = self.client.image_to_video(
                image=image_bytes,
                prompt=prompt,
                model=model,
                num_frames=25,
                fps=5,
                width=512,
                height=512,
                num_inference_steps=25,
                guidance_scale=6.0
            )
            return video_bytes
        except Exception as e:
            logger.warning(f"HF 视频模型 {model} 失败: {e}")
            # 直接返回 None，触发本地合成
            return None


class TTSGenerator:
    """Edge TTS 本地语音合成 - 多音色回退"""

    def __init__(self):
        self.voices_config = self._load_voices()
        # 按优先级排序的备选音色（按类别分组）
        self.fallback_voices = [
            "zh-CN-Xiaoxiao",    # 慈祥女声
            "zh-CN-Xiaoyi",      # 知性女声
            "zh-CN-Xiaohan",     # 深情女声
            "zh-CN-Yunxi",       # 磁性男声
            "zh-CN-Yunyang",     # 稳重男声
            "zh-CN-Yunhao",      # 亲切男声
        ]

    def _load_voices(self) -> Dict:
        import yaml
        with open(CONFIG_DIR / "tts_voices.yaml", 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def pick_voice(self, topic_category: str = "default") -> Dict:
        strategy = self.voices_config.get("default_strategy", {})
        preferred_name = strategy.get(topic_category, strategy.get("default", "zh-CN-Yunxi"))
        
        # 先尝试首选音色
        for category in ["warm_male", "warm_female", "dialect"]:
            for v in self.voices_config["voices"][category]:
                if v["name"] == preferred_name:
                    logger.info(f"使用首选音色: {preferred_name}")
                    return v
        
        # 首选不可用，尝试备选
        logger.warning(f"首选音色 {preferred_name} 不可用，尝试备选...")
        for fallback_name in self.fallback_voices:
            for category in ["warm_male", "warm_female", "dialect"]:
                for v in self.voices_config["voices"][category]:
                    if v["name"] == fallback_name:
                        logger.info(f"使用备选音色: {fallback_name}")
                        return v
        
        # 兜底：返回第一个可用的
        return self.voices_config["voices"]["warm_male"][0]

    async def _synthesize_with_fallback(self, text: str, voice_config: Dict, output_path: Path) -> None:
        """尝试多个音色合成，直到成功"""
        voice_names = [voice_config["name"]] + [v for v in self.fallback_voices if v != voice_config["name"]]
        
        last_error = None
        for voice_name in voice_names:
            try:
                logger.info(f"尝试 TTS 音色: {voice_name}")
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=voice_name,
                    rate=voice_config.get("rate", "+0%"),
                    volume=voice_config.get("volume", "+0%"),
                    pitch=voice_config.get("pitch", "+0Hz")
                )
                await communicate.save(str(output_path))
                logger.info(f"TTS 音色 {voice_name} 合成成功")
                return
            except Exception as e:
                logger.warning(f"TTS 音色 {voice_name} 失败: {e}")
                continue
        
        raise RuntimeError(f"所有 TTS 音色均失败: {last_error}")

    def synthesize_sync(self, text: str, voice_config: Dict, output_path: Path) -> None:
        asyncio.run(self._synthesize_with_fallback(text, voice_config, output_path))


class AssetGenerator:
    """素材生成总调度"""

    def __init__(self, cf_account_id: str, cf_api_token: str, hf_token: str, siliconflow_key: str = None):
        self.image_gen = ImageGenerator(
            siliconflow_key=siliconflow_key,
            cf_account_id=cf_account_id,
            cf_api_token=cf_api_token
        )
        self.video_gen = VideoGenerator(hf_token)
        self.tts_gen = TTSGenerator()

    def _local_video_from_image(self, image_bytes: bytes, output_path: Path, duration: int = 5):
        """从单张图片生成视频：缩放+淡入淡出+缩放动画"""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            tmp_img.write(image_bytes)
            tmp_img_path = tmp_img.name
        
        try:
            # 使用 ffmpeg 生成视频：缩放填充 + 缓慢缩放动画 + 淡入淡出
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", tmp_img_path,
                "-vf", (
                    f"scale=1080:1920:force_original_aspect_ratio=increase,"
                    f"crop=1080:1920,"
                    f"zoompan=z='min(zoom+0.0015,1.15)':d={duration*30}:s=1080x1920,"
                    f"fade=t=in:st=0:d=1,fade=t=out:st={duration-1}:d=1,"
                    f"setsar=1"
                ),
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                str(output_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        finally:
            try:
                os.unlink(tmp_img_path)
            except:
                pass

    def generate_all(self, script: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
        assets = AssetPaths(run_dir, script)
        scenes = script["scenes"]

        # 1. 生成配图
        logger.info("生成分镜配图...")
        image_paths = []
        for i, scene in enumerate(scenes):
            img_path = assets.image_path(i + 1)
            if not img_path.exists():
                img_bytes = self.image_gen.generate(scene["image_prompt"])
                img_path.write_bytes(img_bytes)
                check_result = check_image_compliance(img_path)
                if not check_result["passed"]:
                    logger.warning(f"场景 {i+1} 配图合规不通过: {check_result['issues']}")
            image_paths.append(str(img_path))

        # 2. 生成视频片段（HF 失败则本地合成）
        logger.info("生成视频片段...")
        video_paths = []
        for i, scene in enumerate(scenes):
            vid_path = assets.video_path(i + 1)
            if not vid_path.exists():
                img_bytes = Path(image_paths[i]).read_bytes()
                vid_bytes = self.video_gen.generate_i2v(img_bytes, scene["video_prompt"])
                
                if vid_bytes is None:
                    # 本地 ffmpeg 合成：从单张图片生成 5 秒视频（缩放+淡入淡出）
                    logger.info(f"场景 {i+1} 使用本地 ffmpeg 合成视频...")
                    self._local_video_from_image(img_bytes, vid_path, duration=5)
                    vid_bytes = vid_path.read_bytes()
                else:
                    vid_path.write_bytes(vid_bytes)
                
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

        # 5. 准备 BGM
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
        text = script.get("title", "") + " " + " ".join(script.get("tags", []))
        if any(kw in text for kw in ["亲", "爱", "情", "孙", "子", "女", "夫", "妻", "伴"]):
            return "亲情温情"
        if any(kw in text for kw in ["智慧", "学", "技", "艺", "医", "工", "教", "书"]):
            return "生活智慧"
        return "时代记忆"

    def _build_cover_prompt(self, script: Dict[str, Any]) -> str:
        return f"{script['cover_title']}, {script['cover_subtitle']}, {script['title']}, warm nostalgic cinematic lighting, 3:4 aspect ratio, space for text overlay"

    def _prepare_bgm(self, mood: str, output_path: Path) -> None:
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "30", "-c:a", "libmp3lame", "-b:a", "128k", str(output_path)
        ], check=False, capture_output=True)
        logger.info("BGM 占位文件已生成（静音），建议替换为版权清晰的音乐")


@dataclass
class AssetPaths:
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


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    cf_id = os.getenv("CF_ACCOUNT_ID")
    cf_token = os.getenv("CF_API_TOKEN")
    hf_token = os.getenv("HF_TOKEN")
    sf_key = os.getenv("SILICONFLOW_API_KEY")

    if not any([sf_key, cf_id and cf_token]):
        print("请设置 SILICONFLOW_API_KEY 或 CF_ACCOUNT_ID+CF_API_TOKEN")
        exit(1)

    img_gen = ImageGenerator(siliconflow_key=sf_key, cf_account_id=cf_id, cf_api_token=cf_token)
    img = img_gen.generate("elderly couple drinking tea in garden, warm sunset, cinematic")
    Path("test_image.png").write_bytes(img)
    print("测试图片已生成: test_image.png")