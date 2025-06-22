import json
import logging
import os
import platform
import random
import shutil
import socket
import subprocess
import tempfile
import time
from asyncio import as_completed
from concurrent.futures import ThreadPoolExecutor
import requests
from common import constants
from common.constants import CORE_PATH, TEST_URLS, DEBUG_MODE, CONNECTION_TIMEOUT
from common.decorators import timer
from config.settings import Settings


class Tester:
    def __init__(self, name):
        self.name = name

    def run(self):
        print(f"Running tests for {self.name}")


@timer(unit="ms")
def test_all_nodes_latency(
        nodes: list[dict],
        max_workers: int | None = None
) -> list[dict]:
    """
    并发测试各节点延迟，返回有效节点列表，并打印详细进度提示。
    """
    valid: list[dict] = []
    total = len(nodes)
    done = 0
    max_workers = Settings.THREAD_POOL_SIZE if max_workers is None else max_workers
    logging.info(f"开始测试节点延迟，总共 {total} 个节点，使用线程池最大并发数：{max_workers}")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # 提交所有任务
        future_to_node = {pool.submit(process_node, node): node for node in nodes}

        for future in as_completed(future_to_node):
            node = future_to_node[future]
            done += 1

            # 标识该节点的简要标识（优先 id，其次 uri，其次索引）
            nid = f"{node.get("server")}:{node.get("port", 'N/A')}" \
                if node.get("server") and node.get("port") else f"index#{done}"
            try:
                result = future.result()
                if result:
                    # 假设 result 中包含延迟字段 'latency'
                    latency = result.get("latency")
                    logging.info(f"[{done}/{total}] ✓ 节点 {nid} 测试通过" +
                                 (f"，延迟：{latency} ms" if latency is not None else ""))
                    valid.append(result)
                else:
                    logging.info(f"[{done}/{total}] ✗ 节点 {nid} 无效，已跳过")
            except Exception as e:
                logging.info(f"[{done}/{total}] ⚠ 节点 {nid} 测试异常：{e!r}")

    logging.info(f"\n测试完成：共处理 {total} 个节点，其中 {len(valid)} 个有效，{total - len(valid)} 个无效/失败")
    return valid


def process_node(node):
    """处理单个节点，添加延迟信息"""
    if not node or 'name' not in node or 'server' not in node:
        return None

    # logging.info(f"测试节点: {node['name']} [{node['type']}] - {node['server']}:{node['port']}")
    latency = _test_latency(node)

    # 过滤掉延迟为0ms或连接失败的节点或者连接超过1000ms
    if latency < 0 or latency > 1000:
        # status = "连接失败" if latency == -1 else "延迟为0ms"
        # logging.info(f"节点: {node['name']} ，{status}，跳过")
        return None

    # 更新节点名称，添加延迟信息
    node['name'] = f"{node['name']} [{latency}ms]"
    logging.info(f"有效节点: {node['name']} ，延迟: {latency}ms")
    return node


def _test_latency(node):
    """测试节点延迟"""
    # 必须有核心程序才能进行测试
    if not CORE_PATH:
        logging.info(f"未找到核心程序，无法测试节点: {node['name']}")
        return -1

    # 使用核心程序进行精确测试
    latency = _test_node_latency(node)

    return latency


def _test_node_latency(node):
    """使用核心程序测试节点延迟"""
    if not CORE_PATH:
        if DEBUG_MODE:
            logging.info("未找到核心程序，无法进行延迟测试")
        return -1

    # 为测试创建临时目录
    temp_dir = tempfile.mkdtemp(prefix="node_test_")
    config_file = os.path.join(temp_dir, "config.json")

    # 获取一个可用端口
    local_port = find_available_port()

    # 生成配置文件
    config = generate_v2ray_config(node, local_port)
    if not config:
        shutil.rmtree(temp_dir)
        return -1

    with open(config_file, 'w') as f:
        json.dump(config, f)

    # 启动核心进程
    core_process = None
    try:
        # 设置代理环境变量，使用SOCKS代理
        proxies = {
            'http': f'socks5://127.0.0.1:{local_port}',
            'https': f'socks5://127.0.0.1:{local_port}'
        }

        # 在Windows上，使用CREATE_NO_WINDOW标志隐藏控制台窗口
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        # 启动核心程序
        core_process = subprocess.Popen(
            [CORE_PATH, "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )

        # 等待核心程序启动
        time.sleep(3)

        # 测试连接延迟 - 不再使用重试机制
        start_time = time.perf_counter()

        # 按顺序尝试不同的测试URL
        for test_url in TEST_URLS:
            try:
                if DEBUG_MODE:
                    logging.info(f"测试节点: {node['name']} - 尝试URL: {test_url}")

                response = requests.get(
                    test_url,
                    proxies=proxies,
                    headers=constants.HEADERS,
                    timeout=CONNECTION_TIMEOUT
                )

                if response.status_code in [200, 204]:
                    latency = int((time.perf_counter() - start_time) * 1000)
                    if DEBUG_MODE:
                        logging.info(f"测试成功: {node['name']} - URL: {test_url} - 延迟: {latency}ms")
                    return latency
                else:
                    if DEBUG_MODE:
                        logging.info(f"测试URL状态码错误: {response.status_code}")
            except Exception as e:
                if DEBUG_MODE:
                    logging.info(f"测试失败: {test_url} - 错误: {str(e)}")
                continue  # 尝试下一个URL

        # 所有URL测试都失败
        if DEBUG_MODE:
            logging.info(f"节点 {node['name']} 所有测试URL都失败")
        return -1

    except Exception as e:
        if DEBUG_MODE:
            logging.info(f"测试节点 {node['name']} 时发生错误: {str(e)}")
        return -1

    finally:
        # 清理资源
        if core_process:
            core_process.terminate()
            try:
                core_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                core_process.kill()

        # 删除临时目录
        try:
            shutil.rmtree(temp_dir)
        except:
            pass


def find_available_port(start_port=10000, end_port=60000):
    """查找可用的端口"""
    while True:
        port = random.randint(start_port, end_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('127.0.0.1', port))
            sock.close()
            return port
        except:
            sock.close()
            continue


def generate_v2ray_config(node, local_port):
    """根据节点信息生成V2Ray配置文件，采用与V2RayN相同的配置方式"""
    config = {
        "inbounds": [
            {
                "port": local_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {
                    "auth": "noauth",  # 不需要认证
                    "udp": True  # 支持UDP
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"]
                }
            }
        ],
        "outbounds": [
            # 出站连接将根据节点类型生成
        ],
        "log": {
            "loglevel": "none"  # 禁止日志输出，减少干扰
        }
    }

    # 根据节点类型配置出站连接，参考V2RayN的配置方式
    if node['type'] == 'vmess':
        # 基本VMess配置
        outbound = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": node['server'],
                        "port": node['port'],
                        "users": [
                            {
                                "id": node['uuid'],
                                "alterId": node.get('alterId', 0),
                                "security": node.get('cipher', 'auto')
                            }
                        ]
                    }
                ]
            },
            "streamSettings": {
                "network": node.get('network', 'tcp'),
                "security": "tls" if node.get('tls', False) else "none"
            }
        }

        # 添加网络特定配置，参考V2RayN的配置
        if node.get('network') == 'ws':
            outbound["streamSettings"]["wsSettings"] = {
                "path": node.get('path', '/'),
                "headers": {
                    "Host": node.get('host', node['server'])
                }
            }
        elif node.get('network') == 'h2':
            outbound["streamSettings"]["httpSettings"] = {
                "path": node.get('path', '/'),
                "host": [node.get('host', node['server'])]
            }
        elif node.get('network') == 'quic':
            outbound["streamSettings"]["quicSettings"] = {
                "security": node.get('quicSecurity', 'none'),
                "key": node.get('quicKey', ''),
                "header": {
                    "type": node.get('headerType', 'none')
                }
            }
        elif node.get('network') == 'grpc':
            outbound["streamSettings"]["grpcSettings"] = {
                "serviceName": node.get('path', ''),
                "multiMode": node.get('multiMode', False)
            }
        elif node.get('network') == 'tcp':
            if node.get('headerType') == 'http':
                outbound["streamSettings"]["tcpSettings"] = {
                    "header": {
                        "type": "http",
                        "request": {
                            "path": [node.get('path', '/')],
                            "headers": {
                                "Host": [node.get('host', '')]
                            }
                        }
                    }
                }

        # TLS相关设置
        if node.get('tls'):
            outbound["streamSettings"]["tlsSettings"] = {
                "serverName": node.get('sni', node.get('host', node['server'])),
                "allowInsecure": node.get('allowInsecure', False)
            }

        config["outbounds"] = [outbound]
    elif node['type'] == 'trojan':
        # 增强Trojan配置
        config["outbounds"] = [{
            "protocol": "trojan",
            "settings": {
                "servers": [
                    {
                        "address": node['server'],
                        "port": node['port'],
                        "password": node['password']
                    }
                ]
            },
            "streamSettings": {
                "network": node.get('network', 'tcp'),
                "security": "tls",
                "tlsSettings": {
                    "serverName": node.get('sni', node.get('host', node['server'])),
                    "allowInsecure": node.get('allowInsecure', False)
                }
            }
        }]

        # 添加网络特定配置
        if node.get('network') == 'ws':
            config["outbounds"][0]["streamSettings"]["wsSettings"] = {
                "path": node.get('path', '/'),
                "headers": {
                    "Host": node.get('host', node['server'])
                }
            }
    elif node['type'] == 'vless':
        # 增强VLESS配置
        config["outbounds"] = [{
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": node['server'],
                        "port": node['port'],
                        "users": [
                            {
                                "id": node['uuid'],
                                "encryption": "none",
                                "flow": node.get('flow', '')
                            }
                        ]
                    }
                ]
            },
            "streamSettings": {
                "network": node.get('network', 'tcp'),
                "security": "tls" if node.get('tls', False) else "none"
            }
        }]

        # 添加网络特定配置
        if node.get('network') == 'ws':
            config["outbounds"][0]["streamSettings"]["wsSettings"] = {
                "path": node.get('path', '/'),
                "headers": {
                    "Host": node.get('host', node['server'])
                }
            }
        elif node.get('network') == 'grpc':
            config["outbounds"][0]["streamSettings"]["grpcSettings"] = {
                "serviceName": node.get('path', ''),
                "multiMode": node.get('multiMode', False)
            }

        # TLS相关设置
        if node.get('tls'):
            config["outbounds"][0]["streamSettings"]["tlsSettings"] = {
                "serverName": node.get('sni', node.get('host', node['server'])),
                "allowInsecure": node.get('allowInsecure', False)
            }
    elif node['type'] == 'ss':
        # Shadowsocks配置
        config["outbounds"] = [{
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": node['server'],
                        "port": node['port'],
                        "method": node['cipher'],
                        "password": node.get('password', 'None')
                    }
                ]
            }
        }]
    elif node['type'] == 'socks':
        # SOCKS配置
        outbound = {
            "protocol": "socks",
            "settings": {
                "servers": [
                    {
                        "address": node['server'],
                        "port": node['port']
                    }
                ]
            }
        }

        # 如果有用户名和密码，添加到配置中
        if node.get('username') and node.get('password'):
            outbound["settings"]["servers"][0]["users"] = [
                {
                    "user": node['username'],
                    "pass": node['password']
                }
            ]

        config["outbounds"] = [outbound]
    elif node['type'] in ['http', 'https']:
        # HTTP/HTTPS配置
        outbound = {
            "protocol": "http",
            "settings": {
                "servers": [
                    {
                        "address": node['server'],
                        "port": node['port']
                    }
                ]
            }
        }

        # 如果有用户名和密码，添加到配置中
        if node.get('username') and node.get('password'):
            outbound["settings"]["servers"][0]["users"] = [
                {
                    "user": node['username'],
                    "pass": node['password']
                }
            ]

        config["outbounds"] = [outbound]
    else:
        # 对于不完全支持的协议，使用简单配置
        if DEBUG_MODE:
            logging.info(f"警告: 节点类型 {node['type']} 可能不被完全支持，使用基本配置")
        return None

    return config
