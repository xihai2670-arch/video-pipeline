"""合规检查模块"""
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from utils import load_text_lines, ROOT_DIR, CONFIG_DIR

logger = logging.getLogger(__name__)


class ComplianceChecker:
    """内容合规检查器"""

    def __init__(self):
        self.sensitive_words = self._load_sensitive_words()
        self.compiled_patterns = self._compile_patterns()

    def _load_sensitive_words(self) -> List[str]:
        """加载敏感词库"""
        path = CONFIG_DIR / "sensitive_words.txt"
        words = load_text_lines(path)
        logger.info(f"加载敏感词 {len(words)} 个")
        return words

    def _compile_patterns(self) -> List[re.Pattern]:
        """编译正则模式（词边界匹配）"""
        patterns = []
        for word in self.sensitive_words:
            # 中文词边界处理：前后为非字母数字下划线或字符串首尾
            pattern = r'(?<![\w\u4e00-\u9fff])' + re.escape(word) + r'(?![\w\u4e00-\u9fff])'
            try:
                patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                logger.warning(f"敏感词正则编译失败: {word}")
        return patterns

    def check_text(self, text: str, context: str = "") -> List[Dict[str, Any]]:
        """检查单段文本，返回问题列表"""
        issues = []
        for pattern in self.compiled_patterns:
            for match in pattern.finditer(text):
                issues.append({
                    "type": "sensitive_word",
                    "severity": "high",
                    "detail": f"检测到敏感词: {match.group()}",
                    "location": f"{context}[{match.start()}:{match.end()}]",
                    "matched_word": match.group()
                })
        return issues

    def check_script(self, script: Dict[str, Any]) -> Dict[str, Any]:
        """完整检查脚本（标题、封面、旁白、字幕、标签）"""
        all_issues = []

        # 1. 标题检查
        title = script.get("title", "")
        if title:
            all_issues.extend(self.check_text(title, "title"))
            if len(title) > 18:
                all_issues.append({
                    "type": "platform_rule",
                    "severity": "medium",
                    "detail": f"标题过长 ({len(title)}字)，建议 ≤18字",
                    "location": "title"
                })

        # 2. 封面标题检查
        cover_title = script.get("cover_title", "")
        if cover_title:
            all_issues.extend(self.check_text(cover_title, "cover_title"))
            if len(cover_title) > 10:
                all_issues.append({
                    "type": "platform_rule",
                    "severity": "medium",
                    "detail": f"封面大标题过长 ({len(cover_title)}字)，建议 ≤10字",
                    "location": "cover_title"
                })

        cover_subtitle = script.get("cover_subtitle", "")
        if cover_subtitle:
            all_issues.extend(self.check_text(cover_subtitle, "cover_subtitle"))
            if len(cover_subtitle) > 15:
                all_issues.append({
                    "type": "platform_rule",
                    "severity": "low",
                    "detail": f"封面副标题过长 ({len(cover_subtitle)}字)，建议 ≤15字",
                    "location": "cover_subtitle"
                })

        # 3. 旁白全文检查
        scenes = script.get("scenes", [])
        full_narration = " ".join([s.get("narration", "") for s in scenes])
        if full_narration:
            all_issues.extend(self.check_text(full_narration, "narration"))
            # 字数检查
            char_count = len(full_narration)
            if char_count < 400 or char_count > 600:
                all_issues.append({
                    "type": "platform_rule",
                    "severity": "medium",
                    "detail": f"旁白字数 {char_count} 不在建议范围 450-550",
                    "location": "narration"
                })

        # 4. 字幕检查
        for i, scene in enumerate(scenes):
            subtitle = scene.get("subtitle", "")
            if subtitle:
                all_issues.extend(self.check_text(subtitle, f"subtitle[{i}]"))
                if len(subtitle) > 20:
                    all_issues.append({
                        "type": "platform_rule",
                        "severity": "low",
                        "detail": f"字幕过长 ({len(subtitle)}字)，建议 ≤20字",
                        "location": f"subtitle[{i}]"
                    })

        # 5. 标签检查
        tags = script.get("tags", [])
        for i, tag in enumerate(tags):
            all_issues.extend(self.check_text(tag, f"tags[{i}]"))

        # 6. 场景数检查
        if len(scenes) != 6:
            all_issues.append({
                "type": "platform_rule",
                "severity": "high",
                "detail": f"场景数必须为 6 个（30秒/5秒），当前 {len(scenes)} 个",
                "location": "scenes"
            })

        # 7. 版权风险启发式检查
        copyright_issues = self._check_copyright_risk(script)
        all_issues.extend(copyright_issues)

        # 汇总
        high_issues = [i for i in all_issues if i["severity"] == "high"]
        passed = len(high_issues) == 0

        return {
            "passed": passed,
            "issues": all_issues,
            "high_count": len(high_issues),
            "medium_count": len([i for i in all_issues if i["severity"] == "medium"]),
            "low_count": len([i for i in all_issues if i["severity"] == "low"]),
            "suggestions": self._generate_suggestions(all_issues)
        }

    def _check_copyright_risk(self, script: Dict[str, Any]) -> List[Dict[str, Any]]:
        """版权风险启发式检查"""
        issues = []
        full_text = script.get("title", "") + " " + " ".join([s.get("narration", "") for s in script.get("scenes", [])])

        # 检查知名 IP 关键词
        ip_keywords = [
            "哈利波特", "漫威", "迪士尼", "皮克斯", "吉卜力", "宫崎骏",
            "三体", "流浪地球", "红楼梦", "西游记", "水浒传", "三国演义",
            "周杰伦", "邓丽君", "张学友", "刘德华", "郭德纲", "相声"
        ]

        for kw in ip_keywords:
            if kw in full_text:
                issues.append({
                    "type": "copyright",
                    "severity": "high",
                    "detail": f"疑似包含知名IP关键词: {kw}",
                    "location": "full_text"
                })

        return issues

    def _generate_suggestions(self, issues: List[Dict[str, Any]]) -> List[str]:
        """根据问题生成修改建议"""
        suggestions = []
        if any(i["type"] == "sensitive_word" for i in issues):
            suggestions.append("替换或删除敏感词，改用委婉表达")
        if any(i["type"] == "platform_rule" and "过长" in i["detail"] for i in issues):
            suggestions.append("精简标题/字幕字数，符合平台限制")
        if any(i["type"] == "copyright" for i in issues):
            suggestions.append("移除真人真事/知名IP引用，改为原创虚构故事")
        if any(i["type"] == "platform_rule" and "场景数" in i["detail"] for i in issues):
            suggestions.append("调整分镜为恰好 6 个场景，每个 5 秒")
        if not suggestions:
            suggestions.append("内容合规，无需修改")
        return suggestions


def check_image_compliance(image_path: Path) -> Dict[str, Any]:
    """图片合规检查（占位：对接内容安全 API）"""
    # TODO: 对接阿里云/腾讯云/百度内容安全 API
    # 当前返回通过，实际部署时需实现
    return {
        "passed": True,
        "issues": [],
        "note": "图片合规检查待接入内容安全 API"
    }


def check_video_compliance(video_path: Path) -> Dict[str, Any]:
    """视频合规检查（占位：抽帧+内容安全 API）"""
    # TODO: ffmpeg 抽帧 + 内容安全 API 逐帧检测
    return {
        "passed": True,
        "issues": [],
        "note": "视频合规检查待接入内容安全 API"
    }


if __name__ == "__main__":
    # 简单测试
    checker = ComplianceChecker()
    test_text = "这是一个关于亲情的温馨故事，老伴离世半年，桃树开花了"
    result = checker.check_text(test_text, "test")
    print(json.dumps(result, ensure_ascii=False, indent=2))