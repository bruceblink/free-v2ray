import io
import logging
import os
import platform
import subprocess
import time
import zipfile
from ssl import SSLError
from subprocess import Popen, STARTUPINFO, STARTF_USESHOWWINDOW
from typing import Optional

import requests
from requests import RequestException, Session

from common.constants import XRAY_API_URL, GITHUB_PROXY, HEADERS
from utils.utils import make_session_with_retries


class XrayOrV2RayBooster:
    """下载、安装并启动 Xray/V2Ray 核心程序的工具类。"""

    def __init__(self) -> None:
        # 安装后的可执行文件路径
        self.install_path: Optional[str] = None

    @staticmethod
    def _detect_platform() -> str:
        """
        检测当前操作系统和架构，返回如 'windows-64' 或 'linux-32' 的字符串，
        用于匹配 GitHub Release 中对应的压缩包名称。
        """
        system = platform.system().lower()
        arch = '64' if platform.architecture()[0] == '64bit' else '32'
        return f"{system}-{arch}"

    @staticmethod
    def get_xray_download_url() -> Optional[str]:
        """
        从官方 API 获取最新 Release 信息，并筛选出与当前平台匹配的 .zip 下载链接。
        """
        try:
            resp = requests.get(XRAY_API_URL, timeout=30)
            resp.raise_for_status()
            info = resp.json()
            keyword = XrayOrV2RayBooster._detect_platform()
            for asset in info.get('assets', []):
                name = asset.get('name', '').lower()
                # 匹配平台关键字且文件名以 .zip 结尾
                if keyword in name and name.endswith('.zip'):
                    return asset.get('browser_download_url')
        except (RequestException, ValueError) as e:
            logging.warning(f"获取下载链接失败: {e}")
        return None

    def download_xray_core(self, url: str, timeout: int = 10) -> str:
        """
        下载并解压 Xray Core 压缩包，返回可执行文件的绝对路径。
        - 优先使用直连 URL，失败后尝试通过代理镜像。
        - 解压后在非 Windows 平台上设置可执行权限。
        """
        plat = self._detect_platform()
        base_dir = os.path.join("xray-core", plat)
        exe_name = "xray.exe" if plat.startswith("windows") else "xray"
        target = os.path.join(base_dir, exe_name)

        # 若已存在直接返回
        if os.path.isfile(target):
            logging.debug(f"Xray 已存在于：{target}")
            return target

        # 构造带重试策略的 Session
        session: Session = make_session_with_retries(total_retries=3, backoff_factor=1)
        for attempt_url in (url, f"{GITHUB_PROXY}/{url}"):
            try:
                resp = session.get(attempt_url, timeout=timeout, headers=HEADERS)
                resp.raise_for_status()
                os.makedirs(base_dir, exist_ok=True)
                # 解压 ZIP 到目标目录
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    z.extractall(base_dir)
                    logging.debug(f"xray 已解压到：{base_dir}")
                # Linux/Unix 平台下赋予可执行权限
                if not plat.startswith("windows"):
                    os.chmod(os.path.join(base_dir, exe_name), 0o755)
                self.install_path = target
                return target

            except SSLError:
                # SSL 验证失败时跳过验证重试一次
                session.verify = False
                logging.warning("SSL 验证失败，已跳过验证重试")
            except RequestException as e:
                logging.warning(f"下载失败({attempt_url}): {e}")

            time.sleep(2)  # 简单退避

        raise RuntimeError("所有下载方式均失败，请检查网络或镜像设置")

    def bootstrap_xray(self, config_file: str) -> Popen:
        """
        使用给定的配置文件启动 Xray 子进程。
        - Windows 平台隐藏控制台窗口。
        - 启动失败时立即终止进程并抛出异常。
        """
        if not self.install_path:
            raise RuntimeError("Xray 核心程序未安装，请先调用 download_xray_core")

        startup = None
        # Windows 上隐藏窗口
        if platform.system().lower() == "windows":
            startup = STARTUPINFO()
            startup.dwFlags |= STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE  # type: ignore

        proc = Popen(
            [self.install_path, "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startup
        )
        # 若进程立即退出则视为启动失败
        if proc.poll() is not None:
            proc.kill()
            raise RuntimeError("Xray 启动失败，可能是配置文件错误或程序损坏")
        return proc
