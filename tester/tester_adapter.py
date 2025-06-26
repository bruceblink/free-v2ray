import io
import logging
import os
import platform
import time
import unittest
import zipfile
from abc import ABC, abstractmethod
from ssl import SSLError
from subprocess import Popen
import requests
from requests import RequestException
from common import constants
from common.constants import GITHUB_PROXY, XRAY_API_URL
from utils.utils import make_session_with_retries
import subprocess
import sys
import threading
import time
import os
import signal
import psutil


class ProcessManager:
    def __init__(self, executable_path, *args):
        """
        进程管理器
        :param executable_path: 可执行文件路径
        :param args: 命令行参数
        """
        self.executable_path = executable_path
        self.args = list(args)
        self.process = None
        self.pid = None
        self.stdout_thread = None
        self.stderr_thread = None
        self.stdout_lines = []
        self.stderr_lines = []
        self.running = False

        # Windows特定配置
        self.startupinfo = None
        if sys.platform == "win32":
            self.startupinfo = subprocess.STARTUPINFO()
            self.startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.startupinfo.wShowWindow = subprocess.SW_HIDE

    def start(self) -> bool:
        """启动进程并实时输出日志"""
        if self.is_running():
            print(f"进程已在运行 (PID: {self.pid})")
            return False

        try:
            # 创建进程
            self.process = subprocess.Popen(
                [self.executable_path] + self.args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,  # 行缓冲
                text=True,  # 文本模式
                startupinfo=self.startupinfo
            )
            self.pid = self.process.pid
            self.running = True

            print(f"进程已启动 (PID: {self.pid}): {self.executable_path} {' '.join(self.args)}")

            # 启动线程实时输出日志
            self.stdout_thread = threading.Thread(
                target=self._read_stream,
                args=(self.process.stdout, "STDOUT")
            )
            self.stderr_thread = threading.Thread(
                target=self._read_stream,
                args=(self.process.stderr, "STDERR")
            )

            self.stdout_thread.daemon = True
            self.stderr_thread.daemon = True

            self.stdout_thread.start()
            self.stderr_thread.start()

            return True
        except FileNotFoundError:
            print(f"错误: 找不到可执行文件: {self.executable_path}")
            return False
        except PermissionError:
            print(f"错误: 没有执行权限: {self.executable_path}")
            return False

    def _read_stream(self, stream, stream_name) -> None:
        """从流中读取数据并实时输出"""
        try:
            for line in iter(stream.readline, ''):
                if not line:
                    break
                line = line.rstrip()
                # 实时输出到终端
                print(f"[{stream_name} PID:{self.pid}] {line}")
                # 保存日志
                if stream_name == "STDOUT":
                    self.stdout_lines.append(line)
                else:
                    self.stderr_lines.append(line)
        except ValueError:
            # 当流关闭时可能发生
            pass
        finally:
            stream.close()

    def is_running(self) -> bool:
        """检查进程是否正在运行"""
        return self.running and self.process and (self.process.poll() is None)

    def wait(self) -> int | None:
        """等待进程结束"""
        if self.process:
            return self.process.wait()
        return None

    def stop(self, timeout=5) -> bool:
        """停止进程"""
        if not self.is_running():
            print("进程未运行")
            return True

        print(f"正在停止进程 (PID: {self.pid})...")

        # 优雅终止
        try:
            if sys.platform == "win32":
                self.process.terminate()
            else:
                os.kill(self.pid, signal.SIGTERM)

            # 等待结束
            start_time = time.time()
            while time.time() - start_time < timeout:
                if not self.is_running():
                    print("进程已终止")
                    return True
                time.sleep(0.1)
        except Exception as e:
            print(f"优雅终止失败: {str(e)}")

        # 强制终止
        try:
            self._force_kill()
            print("进程已强制终止")
            return True
        except Exception as e:
            print(f"强制终止失败: {str(e)}")
            return False

    def _force_kill(self) -> None:
        """强制终止进程树"""
        try:
            parent = psutil.Process(self.pid)
            children = parent.children(recursive=True)

            # 终止子进程
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass

            # 终止父进程
            parent.kill()

            # 等待结束
            parent.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
        except Exception:
            # 回退
            self.process.kill()
            self.process.wait()
        finally:
            self.running = False

    def get_logs(self, stream="both", max_lines=None) -> dict:
        """获取日志"""
        result = {}

        if stream in ("both", "stdout"):
            lines = self.stdout_lines
            if max_lines and len(lines) > max_lines:
                lines = lines[-max_lines:]
            result["stdout"] = "\\n".join(lines)

        if stream in ("both", "stderr"):
            lines = self.stderr_lines
            if max_lines and len(lines) > max_lines:
                lines = lines[-max_lines:]
            result["stderr"] = "\\n".join(lines)

        return result

    def __del__(self):
        """确保进程被终止"""
        if self.is_running():
            self.stop()


def main():
    # 创建进程管理器
    process_manager = ProcessManager("xxxx.exe", "-f", "app.yaml")

    # 启动进程并实时输出日志
    if not process_manager.start():
        print("启动失败")
        return

    try:
        # 主线程可以继续工作
        print("主线程正在工作...")

        # 模拟工作
        for i in range(10):
            print(f"主线程工作状态: {i + 1}/10")
            time.sleep(1)

            # 检查进程状态
            if not process_manager.is_running():
                print("子进程已提前退出")
                break

        print("主线程工作完成")
    finally:
        # 确保停止进程
        process_manager.stop()

        # 获取并保存日志
        logs = process_manager.get_logs()
        with open("process_logs.txt", "w") as f:
            f.write("=== STDOUT ===\\n")
            f.write(logs.get("stdout", "") + "\\n\\n")
            f.write("=== STDERR ===\\n")
            f.write(logs.get("stderr", "") + "\\n")

        print("日志已保存到 process_logs.txt")


if __name__ == "__main__":
    main()


class TesterAdapter(ABC):
    """
    tester适配器类，用于适配不同的测试器实现,例如v2ray, xray等。
    """

    def __init__(self, install_path: str) -> None:
        self.install_path = install_path

    @abstractmethod
    def get_download_url(self) -> str | None:
        """获取适配器的下载链接。"""
        pass

    @abstractmethod
    def install_adapter(self, timeout: int = 10) -> str:
        """ 安装适配器。"""
        pass

    @abstractmethod
    def start_adapter(self, config_file: str) -> None:
        """
        启动适配器。
        """
        pass

    @abstractmethod
    def stop_adapter(self, process: Popen) -> None:
        """
        停止适配器。
        """
        pass


class XrayOrV2RayTester(TesterAdapter):
    """
    Xray 或 V2Ray 核心程序下载和安装工具类。
    主要功能包括获取最新版本的下载链接、下载并解压核心程序,以及启动xray进程。
    """

    def __init__(self, install_path: str):
        super().__init__(install_path)

    def get_download_url(self) -> str | None:
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

    def install_adapter(self, timeout: int = 10) -> str:
        """
        下载并解压安装 Xray Core zip，返回解压后的安装目录路径。
        """
        release_url = self.get_download_url()
        if not release_url:
            raise RuntimeError("无法获取 Xray 核心程序的下载链接，请检查网络或更换镜像。")
        is_windows = platform.system() == "Windows"
        install_dir = os.path.join("xray-core", "windows-64" if is_windows else "linux-64")
        self.install_path = os.path.join(install_dir, "xray.exe" if is_windows else "xray")
        if os.path.exists(self.install_path):
            logging.info(f"Xray 已存在于：{self.install_path}")
            return self.install_path
        urls_to_try = [
            f"{release_url}",  # 直连
            f"{GITHUB_PROXY}/{release_url}",  # 代理方式
        ]

        session = make_session_with_retries(total_retries=3, backoff_factor=1)

        for url in urls_to_try:
            try:
                logging.info(f"尝试下载 Xray: {url}")
                resp = session.get(url, timeout=timeout)
                resp.raise_for_status()

                # 解压到指定目录

                os.makedirs(install_dir, exist_ok=True)
                # 解压缩文件
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    z.extractall(install_dir)
                logging.info(f"已解压到：{install_dir}")
                # 设置执行权限（Linux）
                if not is_windows:
                    xray_path = os.path.join(install_dir, "xray")
                    if os.path.exists(xray_path):
                        os.chmod(xray_path, 0o755)
                # 返回绝对路径
                return self.install_path

            except SSLError as ssl_err:
                logging.warning(f"SSL 验证失败: {ssl_err}，尝试跳过验证重试")
            except RequestException as req_err:
                logging.warning(f"下载失败({url}): {req_err}")

            time.sleep(2)

        # 全部方式失败
        raise RuntimeError("所有下载方式均失败，请检查网络或更换镜像。")

    def start_adapter(self, config_file: str) -> Popen | None:
        """
        启动 Xray 核心程序，使用指定的配置文件。
        """
        super().start_adapter(config_file)
        if not self.install_path:
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
            [self.install_path, "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )
        if core_process.poll() is not None:
            raise RuntimeError("Xray 启动失败，可能是配置文件错误或核心程序未正确安装。")
        return core_process

    def stop_adapter(self, process: Popen) -> None:
        super().stop_adapter(process)
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
                logging.info("SubChecker 进程已成功停止。")
            except Exception as e:
                logging.error(f"停止 SubChecker 进程失败: {str(e)}")
        else:
            logging.warning("没有可停止的 SubChecker 进程。")


class SubsCheckTester(TesterAdapter):
    """
    SubChecker 测试器适配器。
    主要功能包括获取最新版本的下载链接、下载并解压核心程序,以及启动SubChecker进程。
    """

    def __init__(self, install_path: str):
        super().__init__(install_path)

    def get_download_url(self) -> str | None:
        """获取SubChecker核心程序的下载链接"""
        try:
            response = requests.get(constants.SUBS_CHECK_URL, timeout=30)
            release_info = response.json()

            # 检测操作系统类型
            is_windows = platform.system() == "Windows"
            is_64bit = platform.architecture()[0] == '64bit'

            # 确定下载文件名
            if is_windows:
                file_keyword = "Windows_x86_64" if is_64bit else "Windows_x86"
            else:  # Linux
                file_keyword = "Linux_x86_64" if is_64bit else "Linux_x86"

            # 查找最新版本的SubChecker发布信息匹配的下载URL
            for asset in release_info['assets']:
                if file_keyword in asset['name'] and asset['name'].endswith('.zip'):
                    return asset['browser_download_url']

            logging.info(f"未找到适合当前平台({file_keyword})的SubsCheck下载链接")
            return None

        except Exception as e:
            logging.warning(f"获取SubChecker下载链接失败: {str(e)}")
            return None

    def install_adapter(self, timeout: int = 10) -> str:
        """
        下载并解压安装 SubChecker zip，返回解压后的安装目录路径。
        """
        release_url = self.get_download_url()
        if not release_url:
            raise RuntimeError("无法获取 Subs-Checker 核心程序的下载链接，请检查网络或更换镜像。")
        is_windows = platform.system() == "Windows"
        install_dir = os.path.join("subs-checker", "windows-64" if is_windows else "linux-64")
        self.install_path = os.path.join(install_dir, "subs-checker.exe" if is_windows else "subs-checker")
        if os.path.exists(self.install_path):
            logging.info(f"SubChecker 已存在于：{self.install_path}")
            return self.install_path
        urls_to_try = [
            f"{release_url}",  # 直连
            f"{GITHUB_PROXY}/{release_url}",  # 代理方式
        ]

        session = make_session_with_retries(total_retries=3, backoff_factor=1)

        for url in urls_to_try:
            try:
                logging.info(f"尝试下载 subs-checker: {url}")
                resp = session.get(url, timeout=timeout)
                resp.raise_for_status()

                # 解压到指定目录
                os.makedirs(install_dir, exist_ok=True)
                # 解压缩文件
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    z.extractall(install_dir)
                logging.info(f"已解压到：{install_dir}")
                # 设置执行权限（Linux）
                if not is_windows:
                    subs_check_path = os.path.join(install_dir, "subs-checker")
                    if os.path.exists(subs_check_path):
                        os.chmod(subs_check_path, 0o755)
                # 返回绝对路径
                return self.install_path

            except SSLError as ssl_err:
                logging.warning(f"SSL 验证失败: {ssl_err}，尝试跳过验证重试")
            except RequestException as req_err:
                logging.warning(f"下载失败({url}): {req_err}")

            time.sleep(2)

        # 全部方式失败
        raise RuntimeError("所有下载方式均失败，请检查网络或更换镜像。")

    def start_adapter(self, config_file: str) -> Popen | None:
        """
        启动 SubChecker 核心程序，使用指定的配置文件。
        """
        super().start_adapter(config_file)
        if not self.install_path:
            raise RuntimeError("SubChecker 核心程序未安装，请先调用 install_adapter 方法。")
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
            [self.install_path, "-f", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )
        if core_process.poll() is not None:
            raise RuntimeError("SubChecker 启动失败，可能是配置文件错误或核心程序未正确安装。")
        return core_process

    def stop_adapter(self, process: Popen) -> None:
        super().stop_adapter(process)
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
                logging.info("SubChecker 进程已成功停止。")
            except Exception as e:
                logging.error(f"停止 SubChecker 进程失败: {str(e)}")
        else:
            logging.warning("没有可停止的 SubChecker 进程。")


class TestSubCheckerTester(unittest.TestCase):
    def setUp(self):
        self.tester = SubsCheckTester(install_path="subs-checker/windows-64/subs-checker")

    def test_get_download_url(self):
        url = self.tester.get_download_url()
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith("https://"))
        self.assertTrue("x86_64" in url)

    def test_install_adapter(self):
        install_path = self.tester.install_adapter(timeout=30)
        self.assertTrue(os.path.exists(install_path))

    def test_start_adapter(self):
        process = self.tester.start_adapter("F:\\Python_Project\\free-v2ray\\conf\\config.yaml")
        self.assertIsNotNone(process)

    def test_stop_adapter(self):
        config_file = "test_config.json"
        process = self.tester.start_adapter(config_file)
        self.tester.stop_adapter(process)
