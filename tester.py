import asyncio
import io
import json
import logging
import os
import platform
import random
import shutil
import socket
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from ssl import SSLError
from subprocess import Popen
from typing import Any, Dict, List, Optional

import aiohttp
import requests
from requests import RequestException

from common import constants
from common.constants import TEST_URLS, CONNECTION_TIMEOUT, XRAY_API_URL, GITHUB_PROXY
from config.settings import Settings
from utils.utils import make_session_with_retries


def find_available_port(start: int = 10000, end: int = 60000) -> int:
    while True:
        port = random.randint(start, end)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue


def generate_v2ray_config(node: Dict[str, Any], local_port: int) -> Optional[Dict[str, Any]]:
    base = {
        "inbounds": [{
            "port": local_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
        }],
        "outbounds": [],
        "log": {"loglevel": "none"}
    }

    builders = {
        'vmess': _build_vmess,
        'trojan': _build_trojan,
        'vless': _build_vless,
        'ss': _build_shadowsocks,
        'socks': _build_socks,
        'http': _build_http,
        'https': _build_http
    }
    builder = builders.get(node['type'])
    if not builder:
        logging.debug(f"警告: 不支持的协议 {node['type']}")
        return None
    outbound = builder(node)
    if outbound:
        base['outbounds'] = [outbound]
    return base


def _common_stream_settings(node: Dict[str, Any], outbound: Dict[str, Any]) -> None:
    net = node.get('network')
    ssl = node.get('tls', False)
    ss = outbound.setdefault('streamSettings', {"network": net, "security": "tls" if ssl else "none"})
    if ssl:
        ss['tlsSettings'] = {
            "serverName": node.get('sni', node.get('host', node['server'])),
            "allowInsecure": node.get('allowInsecure', False)
        }
    if net == 'ws':
        ss['wsSettings'] = {"path": node.get('path', '/'), "headers": {"Host": node.get('host', node['server'])}}
    elif net == 'grpc':
        ss['grpcSettings'] = {"serviceName": node.get('path', ''), "multiMode": node.get('multiMode', False)}
    elif net == 'h2':
        ss['httpSettings'] = {"path": node.get('path', '/'), "host": [node.get('host', node['server'])]}
    elif net == 'quic':
        ss['quicSettings'] = {
            "security": node.get('quicSecurity', 'none'),
            "key": node.get('quicKey', ''),
            "header": {"type": node.get('headerType', 'none')}
        }
    elif net == 'tcp' and node.get('headerType') == 'http':
        ss['tcpSettings'] = {"header": {"type": "http", "request": {"path": [node.get('path', '/')],
                                                                    "headers": {"Host": [node.get('host', '')]}}}}


def _build_vmess(node: Dict[str, Any]) -> Dict[str, Any]:
    outbound = {
        "protocol": "vmess",
        "settings": {"vnext": [{
            "address": node['server'],
            "port": node['port'],
            "users": [{
                "id": node['uuid'],
                "alterId": node.get('alterId', 0),
                "security": node.get('cipher', 'auto')
            }]
        }]}
    }
    _common_stream_settings(node, outbound)
    return outbound


def _build_trojan(node: Dict[str, Any]) -> Dict[str, Any]:
    outbound = {
        "protocol": "trojan",
        "settings": {"servers": [{
            "address": node['server'],
            "port": node['port'],
            "password": node['password']
        }]}
    }
    _common_stream_settings(node, outbound)
    return outbound


def _build_vless(node: Dict[str, Any]) -> Dict[str, Any]:
    outbound = {
        "protocol": "vless",
        "settings": {"vnext": [{
            "address": node['server'],
            "port": node['port'],
            "users": [{"id": node['uuid'], "encryption": "none", "flow": node.get('flow', '')}]
        }]}
    }
    _common_stream_settings(node, outbound)
    return outbound


def _build_shadowsocks(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "protocol": "shadowsocks",
        "settings": {"servers": [{
            "address": node['server'],
            "port": node['port'],
            "method": node['cipher'],
            "password": node.get('password', '')
        }]}
    }


def _build_socks(node: Dict[str, Any]) -> Dict[str, Any]:
    servers = [{"address": node['server'], "port": node['port']}]
    if node.get('username') and node.get('password'):
        servers[0]['users'] = [{"user": node['username'], "pass": node['password']}]
    return {"protocol": "socks", "settings": {"servers": servers}}


def _build_http(node: Dict[str, Any]) -> Dict[str, Any]:
    servers = [{"address": node['server'], "port": node['port']}]
    if node.get('username') and node.get('password'):
        servers[0]['users'] = [{"user": node['username'], "pass": node['password']}]
    return {"protocol": "http", "settings": {"servers": servers}}


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

    def install_xray_core(
            self,
            release_url: str = None,
            timeout: int = 10
    ) -> str:
        """
        下载并解压安装 Xray Core zip，返回解压后的安装目录路径。
        """
        is_windows = platform.system() == "Windows"
        install_dir = os.path.join("xray-core", "windows-64" if is_windows else "linux-64")
        self.xray_install_path = os.path.join(install_dir, "xray.exe" if is_windows else "xray")
        if os.path.exists(self.xray_install_path):
            logging.info(f"Xray 已存在于：{self.xray_install_path}")
            return self.xray_install_path
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
                return self.xray_install_path

            except SSLError as ssl_err:
                logging.warning(f"SSL 验证失败: {ssl_err}，尝试跳过验证重试")
            except RequestException as req_err:
                logging.warning(f"下载失败({url}): {req_err}")

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


class Tester:
    def __init__(self, xray_process: Optional[XrayOrV2RayBooster] = None) -> None:
        self.xray_process = xray_process

    def test_all_nodes_latency(
            self,
            nodes: List[Dict[str, Any]],
            max_workers: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        max_workers = max_workers or Settings.THREAD_POOL_SIZE
        total = len(nodes)
        valid_nodes: List[Dict[str, Any]] = []
        logging.info(
            f"开始测试节点延迟，总共 {total} 个节点，使用线程池最大并发数：{max_workers}"
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._process_node, node): node for node in nodes}
            for idx, future in enumerate(as_completed(futures), 1):
                node = futures[future]
                nid = f"{node.get('server')}:{node.get('port', 'N/A')}" or f"index#{idx}"
                try:
                    result = future.result()
                    if result:
                        logging.info(f"[{idx}/{total}] ✓ 节点 {nid} 测试通过，延迟：{result['latency']} ms")
                        valid_nodes.append(result)
                    else:
                        logging.info(f"[{idx}/{total}] ✗ 节点 {nid} 无效，已跳过")
                except Exception as exc:
                    logging.warning(f"[{idx}/{total}] ⚠ 节点 {nid} 测试异常：{exc!r}")

        logging.info(
            f"测试完成：共处理 {total} 个节点，其中 {len(valid_nodes)} 个有效，"
            f"{total - len(valid_nodes)} 个无效/失败"
        )
        return valid_nodes

    def _process_node(self, node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not node.get('name') or not node.get('server'):
            return None
        latency = self._measure_latency(node)
        if 0 <= latency <= 1000:
            node['latency'] = latency
            node['name'] = f"{node['name']} [{latency}ms]"
            return node
        return None

    def _measure_latency(self, node: Dict[str, Any]) -> int:
        temp_dir = Path(tempfile.mkdtemp(prefix="node_test_"))
        config_path = temp_dir / "config.json"
        port = find_available_port()
        config = generate_v2ray_config(node, port)
        if not config:
            return -1
        config_path.write_text(json.dumps(config))
        proc = self.xray_process.bootstrap_xray(str(config_path))
        try:
            if proc.poll() is not None:
                logging.error(f"无法启动核心进程，检查配置：{config_path}")
                return -1
            proxies = {
                'http': f'socks5://127.0.0.1:{port}',
                'https': f'socks5://127.0.0.1:{port}'
            }
            start = time.perf_counter()
            for url in TEST_URLS:
                try:
                    resp = requests.get(
                        url, proxies=proxies,
                        headers=constants.HEADERS,
                        timeout=CONNECTION_TIMEOUT
                    )
                    if resp.status_code in (200, 204):
                        return int((time.perf_counter() - start) * 1000)
                except requests.RequestException:
                    continue
            return -1
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            shutil.rmtree(temp_dir)


class AsyncTester:
    def __init__(self, xray_process: Optional[XrayOrV2RayBooster] = None) -> None:
        self.xray_process = xray_process

    async def test_all_nodes_latency(
            self,
            nodes: List[Dict[str, Any]],
            max_workers: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        max_workers = max_workers or Settings.THREAD_POOL_SIZE
        total = len(nodes)
        valid_nodes: List[Dict[str, Any]] = []
        sem = asyncio.Semaphore(max_workers)

        logging.info(
            f"开始测试节点延迟，总共 {total} 个节点，使用异步并发数：{max_workers}"
        )

        async def sem_task(idx: int, node: Dict[str, Any]) -> None:
            async with sem:
                nid = f"{node.get('server')}:{node.get('port', 'N/A')}"
                try:
                    result = await self._process_node(node)
                    if result:
                        logging.info(f"[{idx}/{total}] ✓ 节点 {nid} 测试通过，延迟：{result['latency']} ms")
                        valid_nodes.append(result)
                    else:
                        logging.info(f"[{idx}/{total}] ✗ 节点 {nid} 无效，已跳过")
                except Exception as exc:
                    logging.warning(f"[{idx}/{total}] ⚠ 节点 {nid} 测试异常：{exc!r}")

        tasks = [asyncio.create_task(sem_task(i + 1, node)) for i, node in enumerate(nodes)]
        await asyncio.gather(*tasks)

        logging.info(
            f"测试完成：共处理 {total} 个节点，其中 {len(valid_nodes)} 个有效，"
            f"{total - len(valid_nodes)} 个无效/失败"
        )
        return valid_nodes

    async def _process_node(self, node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not node.get('name') or not node.get('server'):
            return None
        latency = await self._measure_latency(node)
        if 0 <= latency <= 1000:
            node['latency'] = latency
            node['name'] = f"{node['name']} [{latency}ms]"
            return node
        return None

    async def _measure_latency(self, node: Dict[str, Any]) -> int:
        temp_dir = Path(tempfile.mkdtemp(prefix="node_test_"))
        proc = None
        try:
            config_path = temp_dir / "config.json"
            port = find_available_port()
            config = generate_v2ray_config(node, port)
            if not config:
                return -1
            config_path.write_text(json.dumps(config))

            # 启动 xray/v2ray 核心进程
            loop = asyncio.get_running_loop()
            proc = await loop.run_in_executor(
                None,
                lambda: self.xray_process.bootstrap_xray(str(config_path))
            )
            if proc.poll() is not None:
                logging.error(f"无法启动核心进程，检查配置：{config_path}")
                return -1

            proxies = {
                'http': f'socks5://127.0.0.1:{port}',
                'https': f'socks5://127.0.0.1:{port}'
            }

            start = time.perf_counter()
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
                for url in TEST_URLS:
                    try:
                        async with session.get(
                                url,
                                proxy=proxies['http'],
                                timeout=CONNECTION_TIMEOUT
                        ) as resp:
                            if resp.status in (200, 204):
                                return int((time.perf_counter() - start) * 1000)
                    except Exception:
                        continue
            return -1
        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
            shutil.rmtree(temp_dir)

