"""视频合成模块 - ffmpeg 拼接、字幕烧录、封面叠加"""
import logging
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from utils import ROOT_DIR

logger = logging.getLogger(__name__)


class VideoComposer:
    """视频合成器"""

    def __init__(self, fps: int = 30, width: int = 1080, height: int = 1920):
        self.fps = fps
        self.width = width
        self.height = height
        # 9:16 竖屏分辨率
        self.target_resolution = f"{width}x{height}"

    def compose(self, asset_paths: Dict[str, Any], script: Dict[str, Any]) -> Path:
        """合成最终视频"""
        final_path = Path(asset_paths["final_video"])
        scenes = script["scenes"]

        # 1. 为每个场景制作：视频缩放/补帧 + 音频对齐 + 字幕烧录
        logger.info("处理各场景片段...")
        scene_files = []
        for i, scene in enumerate(scenes):
            scene_idx = i + 1
            video_in = Path(asset_paths["videos"][i])
            audio_in = Path(asset_paths["audios"][i])
            subtitle = scene.get("subtitle", "")

            scene_out = video_in.parent / f"scene_{scene_idx:02d}_processed.mp4"
            self._process_scene(video_in, audio_in, subtitle, scene_out, scene_idx)
            scene_files.append(scene_out)

        # 2. 拼接所有场景
        logger.info("拼接视频片段...")
        concat_list = final_path.parent / "concat_list.txt"
        with open(concat_list, 'w', encoding='utf-8') as f:
            for sf in scene_files:
                f.write(f"file '{sf.absolute()}'\n")

        # 无损拼接（同编码参数）
        concat_out = final_path.parent / "concatenated.mp4"
        self._run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy", str(concat_out)
        ])

        # 3. 添加 BGM（混音）
        logger.info("混入背景音乐...")
        bgm_path = Path(asset_paths["bgm"])
        bgm_out = final_path.parent / "with_bgm.mp4"
        self._run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(concat_out),
            "-i", str(bgm_path),
            "-filter_complex", "[1:a]volume=0.15[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", str(bgm_out)
        ])

        # 4. 最终编码规范化（确保平台兼容）
        logger.info("最终编码规范化...")
        self._run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(bgm_out),
            "-vf", f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r", str(self.fps),
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            "-t", "30",  # 固定 30 秒
            str(final_path)
        ])

        # 清理中间文件
        for f in scene_files + [concat_list, concat_out, bgm_out]:
            try:
                f.unlink()
            except:
                pass

        logger.info(f"最终视频已生成: {final_path}")
        return final_path

    def _process_scene(self, video_in: Path, audio_in: Path, subtitle: str, output: Path, scene_idx: int) -> None:
        """处理单个场景：视频适配 + 音频替换 + 字幕烧录"""
        # 构建滤镜链
        filter_parts = [
            # 视频：缩放填满 9:16，保持比例居中
            f"[0:v]scale={self.width}:{self.height}:force_original_aspect_ratio=increase,crop={self.width}:{self.height},setsar=1,fps={self.fps}[v]"
        ]

        # 字幕烧录（如果有）
        if subtitle and subtitle.strip():
            # 转义字幕文本
            sub_escaped = subtitle.replace("'", "\\'").replace(":", "\\:")
            filter_parts.append(
                f"[v]drawtext=text='{sub_escaped}':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
                f"fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=10:"
                f"x=(w-text_w)/2:y=h-th-100[vout]"
            )
            video_label = "[vout]"
        else:
            video_label = "[v]"

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_in),
            "-i", str(audio_in),
            "-filter_complex", filter_complex,
            "-map", video_label,
            "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",  # 以最短流为准（旁白长度）
            str(output)
        ]
        self._run_ffmpeg(cmd)

    def generate_cover_with_text(self, cover_path: Path, script: Dict[str, Any], output_path: Path) -> Path:
        """在封面图上叠加标题文字，输出 3:4 封面"""
        title = script.get("cover_title", "")
        subtitle = script.get("cover_subtitle", "")

        if not title and not subtitle:
            # 无文字直接复制
            import shutil
            shutil.copy2(cover_path, output_path)
            return output_path

        # 3:4 分辨率 1080x1440
        cover_w, cover_h = 1080, 1440

        filter_parts = [
            f"[0:v]scale={cover_w}:{cover_h}:force_original_aspect_ratio=increase,crop={cover_w}:{cover_h},setsar=1[v]"
        ]

        if title:
            title_escaped = title.replace("'", "\\'").replace(":", "\\:")
            filter_parts.append(
                f"[v]drawtext=text='{title_escaped}':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=72:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=20:"
                f"x=(w-text_w)/2:y=(h-text_h)/2-80[vout]"
            )
            video_label = "[vout]"
        else:
            video_label = "[v]"

        if subtitle:
            sub_escaped = subtitle.replace("'", "\\'").replace(":", "\\:")
            filter_parts.append(
                f"{video_label}drawtext=text='{sub_escaped}':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
                f"fontsize=40:fontcolor=white@0.9:box=1:boxcolor=black@0.4:boxborderw=10:"
                f"x=(w-text_w)/2:y=(h-text_h)/2+60[vout2]"
            )
            video_label = "[vout2]"

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(cover_path),
            "-filter_complex", filter_complex,
            "-map", video_label,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-frames:v", "1",
            str(output_path)
        ]
        self._run_ffmpeg(cmd)
        return output_path

    def _run_ffmpeg(self, cmd: List[str]) -> subprocess.CompletedProcess:
        """运行 ffmpeg 命令"""
        logger.debug(f"FFmpeg: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"FFmpeg 失败 (code={result.returncode}): {result.stderr}")
            raise RuntimeError(f"FFmpeg 执行失败: {result.stderr}")
        return result


if __name__ == "__main__":
    # 简单测试
    import tempfile
    composer = VideoComposer()
    print("VideoComposer 初始化成功")
    print(f"目标分辨率: {composer.target_resolution}")
    print(f"帧率: {composer.fps}fps")