"""通用工具模块"""
import os
import json
import yaml
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent
CONFIG_DIR = ROOT_DIR / "config"
OUTPUT_DIR = ROOT_DIR / "output"

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_today_run_dir() -> Path:
    """获取今日运行的输出目录（按日期+运行序号）"""
    today = datetime.now().strftime("%Y%m%d")
    # 查找今日已有的运行序号
    existing = list(OUTPUT_DIR.glob(f"{today}_*"))
    run_number = len(existing) + 1
    run_dir = OUTPUT_DIR / f"{today}_{run_number:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def load_yaml(path: Path) -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_text_lines(path: Path) -> List[str]:
    """加载文本文件，按行返回，忽略注释和空行"""
    lines = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                lines.append(line)
    return lines


def save_json(data: Any, path: Path, indent: int = 2) -> None:
    """保存 JSON 文件"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def load_json(path: Path) -> Any:
    """加载 JSON 文件"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def compute_hash(content: str) -> str:
    """计算字符串的 SHA256 短哈希（前 16 位）"""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


def sanitize_filename(name: str, max_len: int = 100) -> str:
    """清理文件名，移除非法字符"""
    import re
    # 替换非法字符
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    # 截断
    if len(name) > max_len:
        name = name[:max_len]
    return name.strip()


def retry_with_backoff(max_attempts: int = 3, base_delay: float = 2.0, max_delay: float = 60.0):
    """指数退避重试装饰器"""
    import time
    import random
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                        logger.warning(f"{func.__name__} 尝试 {attempt + 1}/{max_attempts} 失败: {e}, {delay:.1f}s 后重试")
                        time.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} 重试 {max_attempts} 次均失败: {e}")
            raise last_exception
        return wrapper
    return decorator


class APIClientBase:
    """API 客户端基类，含通用重试和错误处理"""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self.session = None

    def _get_session(self):
        if self.session is None:
            import requests
            self.session = requests.Session()
        return self.session

    def close(self):
        if self.session:
            self.session.close()
            self.session = None


def format_duration(seconds: float) -> str:
    """格式化时长显示"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def estimate_narration_duration(text: str, chars_per_minute: int = 260) -> float:
    """估算旁白时长（秒）"""
    char_count = len(text)
    return (char_count / chars_per_minute) * 60