import random
import asyncio
import json
import logging
import random
import shutil
import socket
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiohttp
import requests
from common import constants
from common.constants import TEST_URLS, CONNECTION_TIMEOUT
from config.settings import Settings
from xray import XrayOrV2RayBooster


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
        proc = None
        try:
            config_path = temp_dir / "config.json"
            port = find_available_port()
            config = generate_v2ray_config(node, port)
            if not config:
                return -1
            config_path.write_text(json.dumps(config))

            proc = self.xray_process.bootstrap_xray(str(config_path))
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

# 用法示例
# async def main():
#     tester = AsyncTester(xray_process)
#     results = await tester.test_all_nodes_latency(nodes_list)
#
# asyncio.run(main())
