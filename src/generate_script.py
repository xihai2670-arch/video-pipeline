"""文案生成模块 - 使用 Gemini 生成结构化短视频脚本"""
import json
import logging
import random
from pathlib import Path
from typing import Dict, List, Any, Optional
from utils import load_yaml, ROOT_DIR, CONFIG_DIR, retry_with_backoff
from compliance import ComplianceChecker

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
except ImportError:
    genai = None
    logger.warning("google-generativeai 未安装，文案生成功能不可用")


class ScriptGenerator:
    """脚本生成器"""

    def __init__(self, api_key: str):
        if genai is None:
            raise RuntimeError("请安装 google-generativeai: pip install google-generativeai")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.templates = load_yaml(CONFIG_DIR / "prompt_templates.yaml")
        self.topics = self._load_topics()
        self.compliance = ComplianceChecker()

    def _load_topics(self) -> List[str]:
        """加载种子选题库"""
        # 内置备选题库（如果没有外部文件）
        default_topics = [
            "老伴离世半年，独自种下的桃树今年开花了",
            "退休教师捡到流浪猫，照顾过程治愈了自己",
            "孙子视频通话教奶奶用智能手机，闹出笑话却拉近了心",
            "女儿远嫁三年未归，母亲把院子种满女儿爱吃的草莓",
            "老父亲偷偷学做抖音，只为给孙女拍成长纪录片",
            "空巢老人收养流浪狗，原来安静的屋里有了脚步声",
            "七十岁大爷给病床前的老伴读半辈子写的日记",
            "儿子送的智能手环报警了，原来是老父亲独自爬山迷路",
            "奶奶把压箱底的旧照片洗成相册，每张背后都写着故事",
            "老两口吵架半世纪，却从未睡过分床",
            "六十岁学剪辑，把儿孙成长拼成《家族简史》发朋友圈",
            "退休医生在社区义诊十年，被邻居称为楼下的半个儿",
            "老奶奶用废纸箱折出孙子梦想的城堡，成了小区网红",
            "七十岁大妈考取心理咨询师证，专治年轻人的丧文化",
            "老爷爷坚持手写信给在外打工的儿子，一封信寄三十年",
            "退休工程师自制助听器，帮同龄人听清儿孙叫唤声",
            "老阿姨把阳台种成空中菜园，邻里共享成了社区食堂",
            "八十岁老人坚持每天游泳，只为不给子女添麻烦",
            "老教授退休后进小学当志愿者，教孩子们种树识鸟",
            "老两口攒十年旅行基金，说走就走走遍大江南北",
            "老裁缝用缝纫机修补孙女婚纱，针脚里藏着三代人的爱",
            "退休厂长带着旧工友修复废弃火车站，成了网红打卡地",
            "老唱片收藏家播放三十年前的方言童谣，唤醒巷子里的童年",
            "老木匠不用图纸凭手感做摇椅，孙子坐上秒睡着",
            "八十岁老中医坚持手写病历，字迹工整如印刷体",
            "老京剧票友在公园唱了一辈子戏，如今教孙辈念唱做打",
            "老照相馆师傅用大画幅相机给邻里拍全家福，免费三十年",
            "退休图书管理员把自家院子改成24小时微图书馆",
            "老船工讲三十年河上往事，录成有声书留给后人",
            "老茶农守着百年茶树，说慢工出细活日子也是熬出来的",
        ]
        # 尝试从文件加载
        topics_file = CONFIG_DIR / "topics.txt"
        if topics_file.exists():
            from utils import load_text_lines
            file_topics = load_text_lines(topics_file)
            if file_topics:
                return file_topics
        return default_topics

    def pick_topic(self, used_topics: Optional[List[str]] = None) -> str:
        """随机选取一个未用过的题目"""
        used = set(used_topics or [])
        available = [t for t in self.topics if t not in used]
        if not available:
            available = self.topics  # 全用完了就允许重复
        return random.choice(available)

    @retry_with_backoff(max_attempts=3, base_delay=5.0)
    def generate_script(self, topic: str) -> Dict[str, Any]:
        """生成单个脚本"""
                system_prompt = self.templates["script_generation"]["system_prompt"]
        # 使用 replace 避免 .format() 解析模板中的 JSON 大括号
        user_prompt = self.templates["script_generation"]["user_prompt"].replace("{{topic}}", topic)
        logger.info(f"生成脚本: {topic[:30]}...")

        response = self.model.generate_content(
            [system_prompt, user_prompt],
            generation_config=genai.GenerationConfig(
                temperature=0.8,
                top_p=0.9,
                top_k=40,
                max_output_tokens=4096,
                response_mime_type="application/json"
            )
        )

        # 解析 JSON
        script = json.loads(response.text)
        script["topic"] = topic  # 保存原始题目

        # 基础字段校验
        script = self._validate_and_fix(script)

        return script

    def _validate_and_fix(self, script: Dict[str, Any]) -> Dict[str, Any]:
        """校验并修正脚本结构"""
        # 确保必要字段存在
        required = ["title", "cover_title", "cover_subtitle", "scenes", "bgm_mood", "tags"]
        for field in required:
            if field not in script:
                script[field] = "" if field != "scenes" else []

        # 确保 6 个场景
        scenes = script.get("scenes", [])
        while len(scenes) < 6:
            scenes.append({
                "index": len(scenes) + 1,
                "duration": 5,
                "narration": "画面待补充",
                "image_prompt": "elderly person, warm lighting, cinematic",
                "video_prompt": "slow camera pan, gentle motion",
                "subtitle": "待补充"
            })
        script["scenes"] = scenes[:6]

        # 修正场景索引
        for i, scene in enumerate(script["scenes"]):
            scene["index"] = i + 1
            scene["duration"] = 5

        return script

    def generate_with_compliance(self, topic: str, max_retries: int = 3) -> Dict[str, Any]:
        """生成并合规检查，不通过则重试"""
        for attempt in range(max_retries):
            script = self.generate_script(topic)
            compliance_result = self.compliance.check_script(script)

            if compliance_result["passed"]:
                logger.info(f"脚本合规通过: {topic[:30]}")
                script["compliance"] = compliance_result
                return script
            else:
                logger.warning(f"脚本合规不通过 (尝试 {attempt+1}/{max_retries}): {compliance_result['high_count']} 个高危问题")
                for issue in compliance_result["issues"]:
                    if issue["severity"] == "high":
                        logger.warning(f"  - {issue['detail']} @ {issue['location']}")

                if attempt < max_retries - 1:
                    # 尝试换个题目重新生成
                    topic = self.pick_topic([topic])

        # 最终仍不通过，返回最后一次结果但标记
        script["compliance"] = compliance_result
        script["compliance_warning"] = "合规检查未通过，请人工复核"
        return script


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("请设置 GEMINI_API_KEY 环境变量")
        exit(1)

    generator = ScriptGenerator(api_key)
    topic = generator.pick_topic()
    script = generator.generate_with_compliance(topic)
    print(json.dumps(script, ensure_ascii=False, indent=2))
