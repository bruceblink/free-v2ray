import io
import logging
import os
import platform
import time
import zipfile
from ssl import SSLError
from subprocess import Popen

import requests
from requests import RequestException

from common.constants import XRAY_API_URL, GITHUB_PROXY
from utils.utils import make_session_with_retries

logger = logging.getLogger(__name__)


class XrayOrV2RayBooster:
    """
    Xray 或 V2Ray 核心程序下载和安装工具类。
    主要功能包括获取最新版本的下载链接、下载并解压核心程序,以及启动xray进程。
    """

    def __init__(self):
        self.xray_install_path = None

    @staticmethod
    def get_xray_download_url() -> str | None:
        """获取Xray核心程序的下载链接"""
        try:
            response = requests.get(XRAY_API_URL, timeout=30)
            release_info = response.json()

            # 检测操作系统类型
            is_windows = platform.system() == "Windows"
            is_64bit = platform.architecture()[0] == '64bit'

            # 确定下载文件名
            if is_windows:
                file_keyword = "windows-64" if is_64bit else "windows-32"
            else:  # Linux
                file_keyword = "linux-64" if is_64bit else "linux-32"

            # 查找最新版本的Xray发布信息匹配的下载URL
            for asset in release_info['assets']:
                if file_keyword in asset['name'].lower() and asset['name'].endswith('.zip'):
                    return asset['browser_download_url']

            logging.info(f"未找到适合当前平台({file_keyword})的Xray下载链接")
            return None

        except Exception as e:
            logging.warning(f"获取Xray下载链接失败: {str(e)}")
            return None

    def download_xray_core(
            self,
            release_url: str = None,
            timeout: int = 10
    ) -> str:
        """
        下载并解压 Xray Core zip，返回解压后的安装目录路径。
        """
        is_windows = platform.system() == "Windows"
        install_dir = os.path.join("xray-core", "windows-64" if is_windows else "linux-64")
        self.xray_install_path = os.path.join(install_dir, "xray.exe" if is_windows else "xray")
        if os.path.exists(self.xray_install_path):
            logger.info(f"Xray 已存在于：{self.xray_install_path}")
            return self.xray_install_path
        urls_to_try = [
            f"{release_url}",  # 直连
            f"{GITHUB_PROXY}/{release_url}",  # 代理方式
        ]

        session = make_session_with_retries(total_retries=3, backoff_factor=1)

        for url in urls_to_try:
            try:
                logger.info(f"尝试下载 Xray: {url}")
                resp = session.get(url, timeout=timeout)
                resp.raise_for_status()

                # 解压到指定目录

                os.makedirs(install_dir, exist_ok=True)
                # 解压缩文件
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    z.extractall(install_dir)
                logger.info(f"已解压到：{install_dir}")
                # 设置执行权限（Linux）
                if not is_windows:
                    xray_path = os.path.join(install_dir, "xray")
                    if os.path.exists(xray_path):
                        os.chmod(xray_path, 0o755)
                # 返回绝对路径
                return self.xray_install_path

            except SSLError as ssl_err:
                logger.warning(f"SSL 验证失败: {ssl_err}，尝试跳过验证重试")
            except RequestException as req_err:
                logger.warning(f"下载失败({url}): {req_err}")

            time.sleep(2)

        # 全部方式失败
        raise RuntimeError("所有下载方式均失败，请检查网络或更换镜像。")

    def bootstrap_xray(self, config_file: str) -> Popen:
        """
        启动 Xray 核心程序，使用指定的配置文件。
        """
        if not self.xray_install_path:
            raise RuntimeError("Xray 核心程序未安装，请先调用 download_xray_core 方法。")
        # 使用 subprocess 启动进程
        import subprocess
        # 在Windows上，使用CREATE_NO_WINDOW标志隐藏控制台窗口
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        # 启动核心程序
        core_process = subprocess.Popen(
            [self.xray_install_path, "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )
        if core_process.poll() is not None:
            raise RuntimeError("Xray 启动失败，可能是配置文件错误或核心程序未正确安装。")
        return core_process


if __name__ == "__main__":
    booster = XrayOrV2RayBooster()
    try:
        install_path = booster.download_xray_core("v25.6.8")
        print(f"Xray 已安装到：{install_path}")
    except Exception as e:
        print(f"下载或安装 Xray 失败: {e}")
        raise
