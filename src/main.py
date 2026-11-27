"""主入口 - 每日视频生成流水线"""
import os
import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent))

from utils import get_today_run_dir, save_json, ROOT_DIR, load_yaml
from generate_script import ScriptGenerator
from generate_assets import AssetGenerator
from compose_video import VideoComposer
from compliance import ComplianceChecker

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT_DIR / "pipeline.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class DailyVideoPipeline:
    """每日视频生成流水线"""

    def __init__(self):
        # 从环境变量读取凭据
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.cf_account_id = os.getenv("CF_ACCOUNT_ID")
        self.cf_api_token = os.getenv("CF_API_TOKEN")
        self.hf_token = os.getenv("HF_TOKEN")

        self._validate_env()

        # 初始化组件
        self.script_gen = ScriptGenerator(self.gemini_key)
        self.asset_gen = AssetGenerator(self.cf_account_id, self.cf_api_token, self.hf_token)
        self.video_composer = VideoComposer()
        self.compliance = ComplianceChecker()

        # 记录已使用的题目（避免重复）
        self.used_topics_file = ROOT_DIR / "used_topics.json"
        self.used_topics = self._load_used_topics()

    def _validate_env(self):
        """验证环境变量"""
        missing = []
        if not self.gemini_key:
            missing.append("GEMINI_API_KEY")
        if not self.cf_account_id:
            missing.append("CF_ACCOUNT_ID")
        if not self.cf_api_token:
            missing.append("CF_API_TOKEN")
        if not self.hf_token:
            missing.append("HF_TOKEN")
        if missing:
            raise RuntimeError(f"缺少环境变量: {', '.join(missing)}")

    def _load_used_topics(self) -> List[str]:
        """加载已用题目记录"""
        if self.used_topics_file.exists():
            try:
                with open(self.used_topics_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return []

    def _save_used_topics(self):
        """保存已用题目记录"""
        with open(self.used_topics_file, 'w', encoding='utf-8') as f:
            json.dump(self.used_topics, f, ensure_ascii=False, indent=2)

    def run(self) -> Dict[str, Any]:
        """执行完整流水线"""
        start_time = datetime.now()
        run_dir = get_today_run_dir()
        logger.info(f"=== 每日视频流水线启动 ===")
        logger.info(f"运行目录: {run_dir}")

        summary = {
            "run_dir": str(run_dir),
            "start_time": start_time.isoformat(),
            "status": "running",
            "steps": {}
        }

        try:
            # 步骤 1: 生成脚本
            logger.info("步骤 1/5: 生成脚本...")
            topic = self.script_gen.pick_topic(self.used_topics)
            script = self.script_gen.generate_with_compliance(topic)

            # 记录已用题目
            self.used_topics.append(topic)
            if len(self.used_topics) > 100:  # 只保留最近 100 个
                self.used_topics = self.used_topics[-100:]
            self._save_used_topics()

            script_path = run_dir / "script.json"
            save_json(script, script_path)
            summary["steps"]["script"] = {
                "status": "success",
                "topic": topic,
                "title": script.get("title"),
                "compliance_passed": script.get("compliance", {}).get("passed", False)
            }

            # 步骤 2: 生成素材
            logger.info("步骤 2/5: 生成素材 (图片/视频/音频/封面)...")
            asset_paths = self.asset_gen.generate_all(script, run_dir)
            summary["steps"]["assets"] = {
                "status": "success",
                "images": len(asset_paths["images"]),
                "videos": len(asset_paths["videos"]),
                "audios": len(asset_paths["audios"]),
                "voice": asset_paths["voice_used"]
            }

            # 步骤 3: 合成视频
            logger.info("步骤 3/5: 合成最终视频...")
            final_video = self.video_composer.compose(asset_paths, script)
            summary["steps"]["compose"] = {
                "status": "success",
                "final_video": str(final_video),
                "size_mb": round(final_video.stat().st_size / 1024 / 1024, 2)
            }

            # 步骤 4: 生成带文字封面
            logger.info("步骤 4/5: 生成带标题封面...")
            cover_with_text = run_dir / "cover_with_title.jpg"
            self.video_composer.generate_cover_with_text(
                Path(asset_paths["cover"]), script, cover_with_text
            )
            summary["steps"]["cover"] = {
                "status": "success",
                "cover_path": str(cover_with_text)
            }

            # 步骤 5: 最终合规检查
            logger.info("步骤 5/5: 最终合规检查...")
            final_compliance = self._final_compliance_check(script, final_video, cover_with_text)
            summary["steps"]["final_compliance"] = final_compliance

            # 生成发布文案
            publish_info = self._generate_publish_info(script, run_dir)
            summary["steps"]["publish"] = publish_info

            # 汇总
            end_time = datetime.now()
            summary["status"] = "success" if final_compliance["passed"] else "compliance_warning"
            summary["end_time"] = end_time.isoformat()
            summary["duration_seconds"] = (end_time - start_time).total_seconds()

            # 保存汇总
            save_json(summary, run_dir / "summary.json")

            logger.info(f"=== 流水线完成: {summary['status']} ===")
            logger.info(f"耗时: {summary['duration_seconds']:.1f} 秒")
            logger.info(f"产出目录: {run_dir}")

            return summary

        except Exception as e:
            logger.exception("流水线执行失败")
            summary["status"] = "failed"
            summary["error"] = str(e)
            summary["end_time"] = datetime.now().isoformat()
            save_json(summary, run_dir / "summary.json")
            raise

    def _final_compliance_check(self, script: Dict[str, Any], video_path: Path, cover_path: Path) -> Dict[str, Any]:
        """最终合规检查（含视频/封面）"""
        # 文案合规（复用脚本生成时的结果）
        script_compliance = script.get("compliance", {})

        # 视频/图片合规（占位，待接入内容安全 API）
        video_compliance = {"passed": True, "issues": [], "note": "视频合规检查待接入内容安全 API"}
        cover_compliance = {"passed": True, "issues": [], "note": "封面合规检查待接入内容安全 API"}

        all_passed = script_compliance.get("passed", False) and video_compliance["passed"] and cover_compliance["passed"]

        return {
            "passed": all_passed,
            "script": script_compliance,
            "video": video_compliance,
            "cover": cover_compliance
        }

    def _generate_publish_info(self, script: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
        """生成发布文案"""
        publish = {
            "title": script.get("title", ""),
            "description": self._build_description(script),
            "tags": script.get("tags", []),
            "cover_path": str(run_dir / "cover_with_title.jpg"),
            "video_path": str(run_dir / "final_video.mp4"),
            "topic": script.get("topic", ""),
            "generated_at": datetime.now().isoformat()
        }
        save_json(publish, run_dir / "publish.json")
        return {"status": "success", "publish_file": str(run_dir / "publish.json")}

    def _build_description(self, script: Dict[str, Any]) -> str:
        """构建发布文案"""
        lines = [
            script.get("title", ""),
            "",
            " ".join([s.get("narration", "")[:50] + "..." for s in script.get("scenes", [])[:2]]),
            "",
            f"#{script.get('tags', [''])[0]} #中老年 #温情故事 #生活感悟",
        ]
        return "\n".join(lines)


def main():
    """CLI 入口"""
    try:
        pipeline = DailyVideoPipeline()
        result = pipeline.run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["status"] in ("success", "compliance_warning") else 1)
    except Exception as e:
        logger.exception("主流程异常")
        print(json.dumps({"status": "failed", "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()