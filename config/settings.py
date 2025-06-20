import logging
import os
from pathlib import Path
from typing import Dict, Any
from unittest import TestCase
import yaml


class Settings:
    # 基础配置
    REQUEST_TIMEOUT = 1
    USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0")

    # 项目根目录路径配置
    BASE_DIR = Path(__file__).parent.parent
    # xray-core存放的文件夹
    XRAY_CORE_DIR = BASE_DIR / "xray-core"
    OUTPUT_DIR = BASE_DIR
    CONFIG_FILE = BASE_DIR / "conf/conf.yaml"

    # 协议配置
    SUPPORTED_PROTOCOLS = ["vmess", "vless"]

    # 线程池大小
    THREAD_POOL_SIZE = min(100, os.cpu_count() * 10)

    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """加载YAML配置文件"""
        if not cls.CONFIG_FILE.exists():
            raise FileNotFoundError(f"配置文件 {cls.CONFIG_FILE} 不存在")

        with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
            logging.info(f"加载配置文件: {cls.CONFIG_FILE}")
            return yaml.safe_load(f)

    @classmethod
    def setup(cls):
        """初始化目录结构"""
        cls.XRAY_CORE_DIR.mkdir(exist_ok=True)
        cls.OUTPUT_DIR.mkdir(exist_ok=True)


class TestSettings(TestCase):

    def setUp(self):
        """设置测试环境"""
        Settings.setup()

    def test_thread_pool_size(self):
        """测试线程池大小"""
        self.assertLessEqual(Settings.THREAD_POOL_SIZE, os.cpu_count() * 10)
        self.assertEqual(Settings.THREAD_POOL_SIZE,100)
        self.assertEqual(os.cpu_count(),24)

