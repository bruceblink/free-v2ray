import base64
import io
import json
import logging
import os
import platform
import random
import re
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote

import requests
import yaml

from common import constants
from common.decorators import timer
from common.logger import Logger
from config.settings import Settings
from utils import utils

# 支持的协议类型列表
SUPPORTED_PROTOCOLS = [
    'vmess://',
    'trojan://',
    'vless://',
    'ss://',
    'ssr://',
    'http://',
    'https://',
    'socks://',
    'socks5://',
    'hysteria://',
    'wireguard://'
]

# 测速相关配置
# 测试URL列表
TEST_URLS = [
    "http://www.gstatic.com/generate_204",  # Google测试
]
CONNECTION_TIMEOUT = 10  # 连接超时时间，单位为秒
DEBUG_MODE = False  # 默认开启调试模式，方便查看处理过程

# 核心程序配置
CORE_PATH = None  # 核心程序路径，将自动检测


def is_github_raw_url(url):
    """判断是否为GitHub的raw URL"""
    return 'raw.githubusercontent.com' in url


def extract_file_pattern(url):
    """从URL中提取文件模式，例如{x}.yaml中的.yaml"""
    match = re.search(r'\{x}(\.[a-zA-Z0-9]+)(?:/|$)', url)
    if match:
        return match.group(1)  # 返回文件后缀，如 '.yaml', '.txt', '.json'
    return None


def get_github_filename(github_url, file_suffix):
    """从GitHub API获取匹配指定后缀的文件名"""
    try:
        logging.info(f"处理GitHub URL: {github_url}")
        # 标准化URL - 移除代理前缀
        url_without_proxy = github_url
        if 'ghproxy.net/' in github_url:
            url_without_proxy = github_url.split('ghproxy.net/', 1)[1]

        # 提取仓库所有者、名称和分支信息
        url_parts = url_without_proxy.replace('https://raw.githubusercontent.com/', '').split('/')
        if len(url_parts) < 3:
            logging.info(f"URL格式不正确: {github_url}")
            return None

        owner = url_parts[0]
        repo = url_parts[1]
        branch = url_parts[2]

        # 处理分支信息
        original_branch = branch
        if 'refs/heads/' in branch:
            branch = branch.split('refs/heads/')[1]

        # 提取文件路径 - 忽略仓库信息和{x}部分
        # 例如：owner/repo/branch/path/to/directory/{x}.yaml -> path/to/directory
        path_parts = '/'.join(url_parts[3:])  # 获取路径部分
        if '{x}' in path_parts:
            directory_path = path_parts.split('/{x}')[0]
        else:
            directory_path = path_parts

        logging.info(f"解析结果: 仓库={owner}/{repo}, 分支={branch}, 路径={directory_path}")

        # 构建GitHub API URL
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{directory_path}"

        # 添加ref参数指定分支
        if branch:
            api_url += f"?ref={branch}"

        logging.info(f"构建的API URL: {api_url}")

        # 使用代理访问GitHub API
        proxy_api_url = f"https://ghproxy.net/{api_url}"
        logging.info(f"尝试通过代理访问: {proxy_api_url}")

        try:
            response = requests.get(proxy_api_url, timeout=30)
            if response.status_code != 200:
                logging.info("代理访问失败，尝试直接访问GitHub API")
                response = requests.get(api_url, timeout=30)
        except Exception as e:
            logging.info(f"代理访问失败: {str(e)}，尝试直接访问")
            response = requests.get(api_url, timeout=30)

        if response.status_code != 200:
            logging.info(f"GitHub API请求失败: {response.status_code} - {api_url}")
            logging.info(f"响应内容: {response.text[:200]}...")
            return None

        # 解析返回的JSON
        files = response.json()
        if not isinstance(files, list):
            logging.info(f"GitHub API返回的不是文件列表: {type(files)}")
            logging.info(f"响应内容: {str(files)[:200]}...")
            return None

        logging.info(f"在目录中找到{len(files)}个文件/目录")

        # 查找匹配后缀的文件
        matching_files = [f['name'] for f in files if f['name'].endswith(file_suffix)]

        if not matching_files:
            logging.info(f"未找到匹配{file_suffix}后缀的文件，目录包含: {[f['name'] for f in files][:10]}")
            return None

        # 排序并选择第一个匹配的文件（通常选择最近的文件）
        matching_files.sort(reverse=True)
        selected_file = matching_files[0]
        logging.info(f"选择文件: {selected_file}")
        return selected_file

    except Exception as e:
        logging.info(f"获取GitHub文件列表出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def format_current_date(url):
    """替换URL中的日期占位符和{x}占位符"""
    # 定义和生成所有可能的日期格式变量
    now = datetime.now()
    date_vars = {
        # 基本日期组件
        'Y': now.strftime('%Y'),  # 年份，如2023
        'm': now.strftime('%m'),  # 月份，如05
        'd': now.strftime('%d'),  # 日期，如09

        # 组合日期格式
        'Ymd': now.strftime('%Y%m%d'),  # 组合格式，如20230509
        'Y-m-d': now.strftime('%Y-%m-%d'),  # 带连字符格式，如2023-05-09
        'Y_m_d': now.strftime('%Y_%m_%d'),  # 带下划线格式，如2023_05_09

        # 额外日期格式
        'Y-m': now.strftime('%Y-%m'),  # 年月，如2023-05
        'Y_m': now.strftime('%Y_%m'),  # 带下划线的年月，如2023_05
        'md': now.strftime('%m%d'),  # 月日，如0509
        'm-d': now.strftime('%m-%d'),  # 带连字符的月日，如05-09
        'm_d': now.strftime('%m_%d'),  # 带下划线的月日，如05_09
    }

    # 处理日期占位符
    try:
        formatted_url = url.format(**date_vars)
    except KeyError as e:
        logging.info(f"URL中包含未支持的日期格式占位符: {e}")
        logging.info(f"支持的日期占位符有: {', '.join(date_vars.keys())}")
        return url  # 返回原始URL，让后续处理决定是否跳过

    # 处理{x}占位符
    if '{x}' in formatted_url:
        # 提取后缀
        file_suffix = extract_file_pattern(formatted_url)
        if file_suffix and is_github_raw_url(formatted_url):
            # 获取GitHub中匹配的文件名
            filename = get_github_filename(formatted_url, file_suffix)
            if filename:
                # 替换{x}占位符为实际文件名
                pattern = r'\{x\}' + re.escape(file_suffix)
                formatted_url = re.sub(pattern, filename, formatted_url)
            else:
                logging.info(f"警告: 未能解析{{x}}占位符, URL: {formatted_url}")

    return formatted_url


def fetch_content(url):
    """获取订阅内容"""
    try:
        # 1. 首先替换日期相关的占位符
        now = datetime.now()
        date_vars = {
            # 基本日期组件
            'Y': now.strftime('%Y'),  # 年份，如2023
            'm': now.strftime('%m'),  # 月份，如05
            'd': now.strftime('%d'),  # 日期，如09

            # 组合日期格式
            'Ymd': now.strftime('%Y%m%d'),  # 组合格式，如20230509
            'Y-m-d': now.strftime('%Y-%m-%d'),  # 带连字符格式，如2023-05-09
            'Y_m_d': now.strftime('%Y_%m_%d'),  # 带下划线格式，如2023_05_09

            # 额外日期格式
            'Y-m': now.strftime('%Y-%m'),  # 年月，如2023-05
            'Y_m': now.strftime('%Y_%m'),  # 带下划线的年月，如2023_05
            'md': now.strftime('%m%d'),  # 月日，如0509
            'm-d': now.strftime('%m-%d'),  # 带连字符的月日，如05-09
            'm_d': now.strftime('%m_%d'),  # 带下划线的月日，如05_09
        }

        # 先将{x}占位符临时替换，以免被format误处理
        temp_marker = "___X_PLACEHOLDER___"
        temporary_url = url.replace("{x}", temp_marker)

        # 尝试使用format方法替换所有日期占位符
        try:
            formatted_url = temporary_url.format(**date_vars)
        except KeyError as e:
            # 如果format失败，尝试手动替换
            logging.info(f"URL中包含未支持的日期格式占位符: {e}")
            logging.info(f"支持的日期占位符有: {', '.join(date_vars.keys())}")
            formatted_url = temporary_url
            # 手动替换常见的日期占位符
            for pattern, replacement in [
                ('{Y_m_d}', now.strftime('%Y_%m_%d')),
                ('{Y-m-d}', now.strftime('%Y-%m-%d')),
                ('{Ymd}', now.strftime('%Y%m%d')),
                ('{Y}', now.strftime('%Y')),
                ('{m}', now.strftime('%m')),
                ('{d}', now.strftime('%d')),
            ]:
                if pattern in formatted_url:
                    formatted_url = formatted_url.replace(pattern, replacement)
                    logging.info(f"手动替换日期占位符 {pattern} 为 {replacement}")

        # 将临时标记替换回{x}
        formatted_url = formatted_url.replace(temp_marker, "{x}")

        # 2. 然后处理{x}占位符 - 现在日期占位符已经被替换
        if '{x}' in formatted_url:
            file_suffix = extract_file_pattern(formatted_url)
            if file_suffix and is_github_raw_url(formatted_url):
                logging.info(f"在URL中找到{{x}}占位符，尝试获取匹配的文件...")
                filename = get_github_filename(formatted_url, file_suffix)
                if filename:
                    pattern = r'\{x\}' + re.escape(file_suffix)
                    formatted_url = re.sub(pattern, filename, formatted_url)
                    logging.info(f"成功替换{{x}}占位符为: {filename}")
                else:
                    logging.info(f"警告: 未能获取匹配{file_suffix}的文件")
            else:
                logging.info(f"警告: 无法处理{{x}}占位符，URL不是GitHub raw链接或找不到文件后缀")

        logging.info(f"实际请求URL: {formatted_url}")

        # 模拟Chrome浏览器请求头，与curl命令类似
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,'
                      '*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Cache-Control': 'no-cache',
            'DNT': '1',
            'Pragma': 'no-cache',
            'Upgrade-Insecure-Requests': '1',
            'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1'
        }

        # 特殊站点处理 - 对特定的站点使用不同的请求方式
        special_sites = ['igdux.top']
        use_session = any(site in formatted_url for site in special_sites)

        if use_session:
            # 使用Session对象来保持cookie等状态
            session = requests.Session()
            # 先发送一个HEAD请求，获取cookie等信息
            session.head(formatted_url, headers=headers, timeout=30)
            response = session.get(formatted_url, headers=headers, timeout=60, stream=True)
        else:
            # 普通请求
            response = requests.get(formatted_url, headers=headers, timeout=60, stream=True)

        response.raise_for_status()

        # 检查Content-Type，确保正确处理各种类型的内容
        content_type = response.headers.get('Content-Type', '').lower()
        # logging.info(f"Content-Type: {content_type}")

        # 处理不同内容类型
        # 1. 处理二进制类型
        if 'application/octet-stream' in content_type or 'application/x-yaml' in content_type:
            content = response.content.decode('utf-8', errors='ignore')
        # 2. 处理明确指定了UTF-8字符集的文本
        elif 'charset=utf-8' in content_type or 'text/plain' in content_type:
            # 尝试多种解码方式
            encodings_to_try = ['utf-8', 'gbk', 'latin1', 'ascii', 'iso-8859-1']
            for encoding in encodings_to_try:
                try:
                    content = response.content.decode(encoding, errors='ignore')
                    # 检查解码是否成功 - 如果包含常见订阅指示符
                    if any(indicator in content for indicator in
                           ['proxies:', 'vmess://', 'trojan://', 'ss://', 'vless://']):
                        # logging.info(f"使用 {encoding} 编码成功解码内容")
                        break
                except UnicodeDecodeError:
                    continue
            else:
                # 如果所有编码都失败，使用默认UTF-8
                content = response.content.decode('utf-8', errors='ignore')

            # 如果网址是特殊站点但仍然得到乱码，尝试拆解HTML标记
            if use_session and not any(
                    indicator in content for indicator in ['proxies:', 'vmess://', 'trojan://', 'ss://', 'vless://']):
                try:
                    # 尝试解析HTML并提取内容
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(response.content, 'html.parser')
                    # 查找所有可能包含订阅信息的元素
                    for element in soup.find_all(['pre', 'code', 'div', 'textarea']):
                        element_text = element.get_text()
                        if any(indicator in element_text for indicator in
                               ['proxies:', 'vmess://', 'trojan://', 'ss://', 'vless://']):
                            logging.info(f"从HTML元素中提取到订阅内容")
                            content = element_text
                            break
                except ImportError:
                    logging.info("未安装BeautifulSoup，跳过HTML解析")
                except Exception as e:
                    logging.info(f"HTML解析错误: {str(e)}")
        # 3. 处理可能是base64编码的内容
        elif 'text/base64' in content_type:
            content = response.content.decode('utf-8', errors='ignore')
        # 4. 处理其他文本格式，如json
        elif 'application/json' in content_type or 'text/' in content_type:
            content = response.content.decode('utf-8', errors='ignore')
        # 5. 默认情况
        else:
            content = response.text

        # 测试内容是否可能是Base64编码
        if not any(indicator in content for indicator in ['proxies:', 'vmess://', 'trojan://', 'ss://', 'vless://']):
            try:
                # 移除空白字符，尝试base64解码
                cleaned_content = re.sub(r'\s+', '', content)
                # 添加适当的填充
                padding = len(cleaned_content) % 4
                if padding:
                    cleaned_content += '=' * (4 - padding)
                # 尝试base64解码
                decoded = base64.b64decode(cleaned_content)
                decoded_text = decoded.decode('utf-8', errors='ignore')

                if any(indicator in decoded_text for indicator in
                       ['proxies:', 'vmess://', 'trojan://', 'ss://', 'vless://']):
                    logging.info("检测到Base64编码的订阅内容，已成功解码")
                    content = decoded_text
            except:
                # 解码失败，继续使用原始内容
                pass

        return content
    except KeyError as e:
        logging.info(f"URL中包含未支持的占位符: {e}")
        return None
    except Exception as e:
        logging.info(f"Error fetching {url}: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def parse_clash_yaml(content):
    """解析Clash配置文件"""
    try:
        data = yaml.safe_load(content)
        if not data:
            return []

        # 直接查找proxies字段，无论它在哪个层级
        if 'proxies' in data:
            if DEBUG_MODE:
                logging.info(f"从YAML中找到 {len(data['proxies'])} 个节点")
            return data['proxies']

        # 如果没有找到proxies字段，尝试其他可能的字段名
        for key in ['proxy-providers', 'Proxy', 'proxys']:
            if key in data and isinstance(data[key], list):
                if DEBUG_MODE:
                    logging.info(f"从YAML的{key}字段中找到 {len(data[key])} 个节点")
                return data[key]

        logging.info("YAML中未找到节点信息")
        return []
    except Exception as e:
        # logging.info(f"解析Clash YAML失败: {str(e)}")
        return []


def parse_v2ray_base64(content):
    """解析V2Ray Base64编码的配置"""
    try:
        # 处理多行base64
        content = content.strip().replace('\n', '').replace('\r', '')
        # 尝试修复可能的编码问题
        try:
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            # 确保内容是ASCII兼容的
            content = content.encode('ascii', 'ignore').decode('ascii')
        except UnicodeError:
            logging.info("Error: Invalid encoding in base64 content")
            return []

        try:
            decoded = base64.b64decode(content + '=' * (-len(content) % 4))
            decoded_str = decoded.decode('utf-8', 'ignore')
        except Exception as e:
            logging.info(f"Error decoding base64 content: {str(e)}")
            return []

        nodes = []
        for line in decoded_str.split('\n'):
            if line.startswith('vmess://') or line.startswith('trojan://'):
                node = parse_v2ray_uri(line)
                if node:
                    nodes.append(node)
        return nodes
    except Exception as e:
        # logging.info(f"Error parsing V2Ray base64: {str(e)}")
        return []


def parse_v2ray_uri(uri):
    """解析V2Ray URI格式的配置"""
    try:
        # 处理vmess协议
        if uri.startswith('vmess://'):
            b64_config = uri.replace('vmess://', '')
            # 确保base64正确填充
            b64_config = b64_config + '=' * (-len(b64_config) % 4)
            try:
                config = json.loads(base64.b64decode(b64_config).decode())
                return {
                    'type': 'vmess',
                    'name': config.get('ps', 'Unknown'),
                    'server': config.get('add', ''),
                    'port': int(config.get('port', 0)),
                    'uuid': config.get('id', ''),
                    'alterId': int(config.get('aid', 0)),
                    'cipher': config.get('type', 'auto'),
                    'tls': config.get('tls', '') == 'tls',
                    'network': config.get('net', 'tcp')
                }
            except json.JSONDecodeError:
                # 某些情况下vmess可能使用非标准格式
                logging.info(f"Non-standard vmess format: {uri}")
                return None

        # 处理trojan协议
        elif uri.startswith('trojan://'):
            parsed = urlparse(uri)
            query = parse_qs(parsed.query)
            return {
                'type': 'trojan',
                'name': query.get('sni', [query.get('peer', ['Unknown'])[0]])[0],
                'server': parsed.hostname or '',
                'port': parsed.port or 443,
                'password': parsed.username or ''
            }

        # 处理vless协议
        elif uri.startswith('vless://'):
            parsed = urlparse(uri)
            query = parse_qs(parsed.query)
            return {
                'type': 'vless',
                'name': query.get('remarks', [query.get('sni', ['Unknown'])[0]])[0],
                'server': parsed.hostname or '',
                'port': parsed.port or 443,
                'uuid': parsed.username or '',
                'tls': query.get('security', [''])[0] == 'tls',
                'flow': query.get('flow', [''])[0],
                'network': query.get('type', ['tcp'])[0]
            }

        # 处理shadowsocks协议
        elif uri.startswith('ss://'):
            # 首先获取#后面的名称部分（如果存在）
            name = 'Unknown'
            if '#' in uri:
                name_part = uri.split('#', 1)[1]
                name = unquote(name_part)
                uri = uri.split('#', 1)[0]  # 移除名称部分以便后续处理

            if '@' in uri:
                # 处理 ss://method:password@host:port
                parsed = urlparse(uri)
                server = parsed.hostname
                port = parsed.port

                # 提取方法和密码
                userinfo = parsed.username
                if userinfo:
                    try:
                        # 有些实现可能会对userinfo进行base64编码
                        decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode()
                        if ':' in decoded:
                            method, password = decoded.split(':', 1)
                        else:
                            method, password = 'aes-256-gcm', userinfo
                    except:
                        # 如果不是base64编码，可能是明文
                        if ':' in userinfo:
                            method, password = userinfo.split(':', 1)
                        else:
                            method, password = 'aes-256-gcm', userinfo
                else:
                    method, password = 'aes-256-gcm', ''

                # 如果查询参数中包含remarks，优先使用它
                query = parse_qs(parsed.query)
                if 'remarks' in query:
                    name = query.get('remarks', ['Unknown'])[0]

                return {
                    'type': 'ss',
                    'name': name,
                    'server': server or '',
                    'port': port or 443,
                    'cipher': method,
                    'password': password
                }
            else:
                # 处理 ss://BASE64(method:password@host:port)
                b64_config = uri.replace('ss://', '')
                try:
                    # 确保base64正确填充
                    b64_config = b64_config + '=' * (-len(b64_config) % 4)

                    config_str = base64.b64decode(b64_config).decode()
                    # 提取方法和密码
                    if '@' in config_str:
                        method_pwd, server_port = config_str.rsplit('@', 1)
                        method, password = method_pwd.split(':', 1)
                        server, port = server_port.rsplit(':', 1)

                        return {
                            'type': 'ss',
                            'name': name,
                            'server': server,
                            'port': int(port),
                            'cipher': method,
                            'password': password
                        }
                except Exception as e:
                    # logging.info(f"Invalid ss URI format: {uri}, error: {str(e)}")
                    return None

        # 处理shadowsocksr协议
        elif uri.startswith('ssr://'):
            b64_config = uri.replace('ssr://', '')
            try:
                # 确保base64正确填充
                b64_config = b64_config + '=' * (-len(b64_config) % 4)
                config_str = base64.b64decode(b64_config).decode()

                # SSR格式: server:port:protocol:method:obfs:base64pass/?obfsparam=base64param&protoparam=base64param
                # &remarks=base64remarks
                parts = config_str.split(':')
                if len(parts) >= 6:
                    server = parts[0]
                    port = parts[1]
                    protocol = parts[2]
                    method = parts[3]
                    obfs = parts[4]

                    # 处理剩余参数
                    password_and_params = parts[5].split('/?', 1)
                    password_b64 = password_and_params[0]
                    password = base64.b64decode(password_b64 + '=' * (-len(password_b64) % 4)).decode()

                    # 提取参数
                    name = 'Unknown'
                    if len(password_and_params) > 1 and 'remarks=' in password_and_params[1]:
                        remarks_b64 = password_and_params[1].split('remarks=', 1)[1].split('&', 1)[0]
                        try:
                            name = base64.b64decode(remarks_b64 + '=' * (-len(remarks_b64) % 4)).decode()
                        except:
                            pass

                    return {
                        'type': 'ssr',
                        'name': name,
                        'server': server,
                        'port': int(port),
                        'protocol': protocol,
                        'cipher': method,
                        'obfs': obfs,
                        'password': password
                    }
            except Exception as e:
                # logging.info(f"Error parsing SSR URI: {str(e)}")
                return None

        # 处理HTTP/HTTPS协议
        elif uri.startswith(('http://', 'https://')):
            parsed = urlparse(uri)
            query = parse_qs(parsed.query)
            return {
                'type': 'http' if uri.startswith('http://') else 'https',
                'name': query.get('remarks', ['Unknown'])[0],
                'server': parsed.hostname or '',
                'port': parsed.port or (80 if uri.startswith('http://') else 443),
                'username': parsed.username or '',
                'password': parsed.password or ''
            }

        # 处理SOCKS协议
        elif uri.startswith(('socks://', 'socks5://')):
            parsed = urlparse(uri)
            query = parse_qs(parsed.query)
            return {
                'type': 'socks',
                'name': query.get('remarks', ['Unknown'])[0],
                'server': parsed.hostname or '',
                'port': parsed.port or 1080,
                'username': parsed.username or '',
                'password': parsed.password or ''
            }

        # 处理hysteria协议
        elif uri.startswith('hysteria://'):
            parsed = urlparse(uri)
            query = parse_qs(parsed.query)
            return {
                'type': 'hysteria',
                'name': query.get('peer', ['Unknown'])[0],
                'server': parsed.hostname or '',
                'port': parsed.port or 443,
                'protocol': query.get('protocol', [''])[0],
                'auth': parsed.username or query.get('auth', [''])[0]
            }

        # 处理wireguard协议
        elif uri.startswith('wireguard://'):
            parsed = urlparse(uri)
            query = parse_qs(parsed.query)
            return {
                'type': 'wireguard',
                'name': query.get('remarks', ['Unknown'])[0],
                'server': parsed.hostname or '',
                'port': parsed.port or 51820,
                'private_key': query.get('privateKey', [''])[0],
                'public_key': query.get('publicKey', [''])[0],
                'allowed_ips': query.get('allowedIPs', ['0.0.0.0/0'])[0]
            }

    except Exception as e:
        # logging.info(f"Error parsing URI: {str(e)}")
        return None


def extract_nodes(content):
    """级联提取节点，按照Base64 -> YAML -> 正则表达式 -> JSON的顺序尝试"""
    if not content:
        return []

    nodes = []
    methods_tried = []

    # 1. 尝试Base64解码提取
    try:
        # 处理多行base64，移除所有空白字符和特殊字符
        cleaned_content = re.sub(r'[\s\n\r\t]+', '', content)
        cleaned_content = re.sub(r'[^A-Za-z0-9+/=]', '', cleaned_content)

        # 确保base64字符串长度是4的倍数
        padding_length = len(cleaned_content) % 4
        if padding_length:
            cleaned_content += '=' * (4 - padding_length)

        # 尝试base64解码
        try:
            decoded_bytes = base64.b64decode(cleaned_content)
            decoded_str = decoded_bytes.decode('utf-8', 'ignore')

            # 检查解码后的内容是否包含任何支持的协议节点
            if any(protocol in decoded_str for protocol in SUPPORTED_PROTOCOLS):
                logging.info("使用Base64解码提取节点")
                methods_tried.append("Base64")
                for line in decoded_str.split('\n'):
                    line = line.strip()
                    if any(line.startswith(protocol) for protocol in SUPPORTED_PROTOCOLS):
                        node = parse_v2ray_uri(line)
                        if node:
                            nodes.append(node)
        except Exception as e:
            # logging.info(f"Base64解码失败或未找到节点: {str(e)}")
            pass
    except Exception as e:
        logging.info(f"Base64预处理失败: {str(e)}")

    # 如果已经提取到节点，直接返回
    if len(nodes) > 0:
        logging.info(f"通过【{methods_tried[-1]}】方法成功提取到{len(nodes)}个节点")
        return nodes

    # 2. 尝试解析YAML格式
    try:
        # 移除HTML标签和特殊标记
        cleaned_content = re.sub(r'<[^>]+>|!&lt;str&gt;', '', content)

        # 更强大的YAML格式检测，查找常见Clash配置特征
        yaml_indicators = [
            'proxies:', 'Proxy:', 'proxy:', 'proxy-providers:',
            'port:', 'socks-port:', 'allow-lan:', 'mode:',
            'type: vmess', 'type: ss', 'type: trojan', 'type: vless'
        ]

        if any(indicator in cleaned_content for indicator in yaml_indicators):
            # logging.info("尝试解析YAML格式内容")
            methods_tried.append("YAML")

            # 尝试直接加载YAML
            try:
                yaml_nodes = parse_clash_yaml(cleaned_content)
                if yaml_nodes:
                    # logging.info(f"从YAML中提取到{len(yaml_nodes)}个节点")
                    nodes.extend(yaml_nodes)
            except Exception as yaml_error:
                logging.info(f"标准YAML解析失败: {str(yaml_error)}")

                # 如果标准解析失败，尝试更宽松的解析方式
                try:
                    # 尝试提取proxies部分
                    proxies_match = re.search(r'proxies:\s*\n([\s\S]+?)(?:\n\w+:|$)', cleaned_content)
                    if proxies_match:
                        proxies_yaml = "proxies:\n" + proxies_match.group(1)
                        yaml_nodes = parse_clash_yaml(proxies_yaml)
                        if yaml_nodes:
                            logging.info(f"从proxies块提取到{len(yaml_nodes)}个节点")
                            nodes.extend(yaml_nodes)
                except Exception as fallback_error:
                    logging.info(f"尝试解析proxies块失败: {str(fallback_error)}")
    except Exception as e:
        logging.info(f"YAML解析过程出错: {str(e)}")

    # 如果已经提取到节点，直接返回
    if len(nodes) > 0:
        logging.info(f"通过【{methods_tried[-1]}】方法成功提取到{len(nodes)}个节点")
        return nodes

    # 3. 尝试使用正则表达式直接提取
    try:
        # logging.info("尝试使用正则表达式直接提取节点")
        methods_tried.append("正则表达式")

        # 为每种支持的协议定义正则表达式并提取
        for protocol in SUPPORTED_PROTOCOLS:
            if protocol == 'vmess://':
                # vmess通常是一个base64编码的字符串
                found_nodes = re.findall(r'vmess://[A-Za-z0-9+/=]+', content)
            elif protocol == 'hysteria://' or protocol == 'wireguard://':
                # 这些协议可能有特殊格式，需要特别处理
                found_nodes = re.findall(f'{protocol}[^"\'<>\\s]+', content)
            else:
                # 对于其他协议，采用通用正则表达式
                found_nodes = re.findall(f'{protocol}[^"\'<>\\s]+', content)

            for uri in found_nodes:
                node = parse_v2ray_uri(uri)
                if node:
                    nodes.append(node)
    except Exception as e:
        logging.info(f"正则表达式提取失败: {str(e)}")

    # 如果已经提取到节点，直接返回
    if len(nodes) > 0:
        logging.info(f"通过【{methods_tried[-1]}】方法成功提取到{len(nodes)}个节点")
        return nodes

    # 4. 尝试解析JSON格式
    try:
        # logging.info("尝试解析JSON格式")
        methods_tried.append("JSON")

        # 清理内容，移除可能的HTML标签和注释
        cleaned_content = re.sub(r'<[^>]+>|/\*.*?\*/|//.*?$', '', content, flags=re.MULTILINE)

        # 尝试解析JSON
        try:
            json_data = json.loads(cleaned_content)
            json_nodes = parse_json_nodes(json_data)
            if json_nodes:
                # logging.info(f"从JSON中提取到{len(json_nodes)}个节点")
                nodes.extend(json_nodes)
        except json.JSONDecodeError as e:
            # 尝试查找内容中的JSON片段
            try:
                # 查找类似于 [{...}] 或 {...} 形式的JSON
                json_matches = re.findall(r'(\[{.*?}]|\{.*?})', cleaned_content, re.DOTALL)
                for json_match in json_matches:
                    try:
                        potential_json = json.loads(json_match)
                        json_nodes = parse_json_nodes(potential_json)
                        if json_nodes:
                            # logging.info(f"从JSON片段中提取到{len(json_nodes)}个节点")
                            nodes.extend(json_nodes)
                            # 找到有效的JSON片段后，不再继续查找
                            break
                    except:
                        continue
            except Exception as extract_error:
                # logging.info(f"尝试提取JSON片段失败: {str(extract_error)}")
                pass
    except Exception as e:
        logging.info(f"JSON解析过程出错: {str(e)}")

    if len(nodes) > 0:
        logging.info(f"通过【{methods_tried[-1]}】方法成功提取到{len(nodes)}个节点")
        return nodes
    else:
        logging.info("未找到任何节点")
        return []


def parse_json_nodes(json_data):
    """从JSON数据中解析节点信息"""
    nodes = []

    # 处理数组形式的JSON
    if isinstance(json_data, list):
        for item in json_data:
            node = parse_single_json_node(item)
            if node:
                nodes.append(node)
    # 处理对象形式的JSON
    elif isinstance(json_data, dict):
        # 检查是否是单个节点
        node = parse_single_json_node(json_data)
        if node:
            nodes.append(node)
        # 检查是否包含节点列表
        elif 'servers' in json_data and isinstance(json_data['servers'], list):
            for server in json_data['servers']:
                node = parse_single_json_node(server)
                if node:
                    nodes.append(node)
        # 检查其他可能的字段名
        for key in ['proxies', 'nodes', 'configs']:
            if key in json_data and isinstance(json_data[key], list):
                for item in json_data[key]:
                    node = parse_single_json_node(item)
                    if node:
                        nodes.append(node)

    return nodes


def parse_single_json_node(item):
    """解析单个JSON节点数据"""
    # 如果不是字典，直接返回
    if not isinstance(item, dict):
        return None

    # 支持Shadowsocks格式
    if ('server' in item and 'server_port' in item and
            'method' in item and 'password' in item):
        try:
            return {
                'type': 'ss',
                'name': item.get('remarks', f"SS-{item['server']}"),
                'server': item['server'],
                'port': int(item['server_port']),
                'cipher': item['method'],
                'password': item['password'],
                'plugin': item.get('plugin', ''),
                'plugin_opts': item.get('plugin_opts', '')
            }
        except Exception as e:
            logging.info(f"解析Shadowsocks节点失败: {str(e)}")
            return None

    # 支持VMess格式
    elif 'add' in item and 'port' in item and 'id' in item:
        try:
            return {
                'type': 'vmess',
                'name': item.get('ps', item.get('remarks', f"VMess-{item['add']}")),
                'server': item['add'],
                'port': int(item['port']),
                'uuid': item['id'],
                'alterId': int(item.get('aid', 0)),
                'cipher': item.get('scy', item.get('security', 'auto')),
                'tls': item.get('tls', '') == 'tls',
                'network': item.get('net', 'tcp'),
                'path': item.get('path', '/'),
                'host': item.get('host', '')
            }
        except Exception as e:
            logging.info(f"解析VMess节点失败: {str(e)}")
            return None

    # 支持Trojan格式
    elif ('server' in item and 'port' in item and 'password' in item and
          item.get('type', '').lower() == 'trojan'):
        try:
            return {
                'type': 'trojan',
                'name': item.get('remarks', f"Trojan-{item['server']}"),
                'server': item['server'],
                'port': int(item['port']),
                'password': item['password'],
                'sni': item.get('sni', item.get('peer', ''))
            }
        except Exception as e:
            logging.info(f"解析Trojan节点失败: {str(e)}")
            return None

    # 支持Clash格式
    elif 'type' in item and 'server' in item and 'port' in item:
        try:
            node_type = item['type'].lower()
            if node_type in ['ss', 'vmess', 'trojan', 'vless', 'http', 'socks']:
                node = {
                    'type': node_type,
                    'name': item.get('name', f"{node_type.upper()}-{item['server']}"),
                    'server': item['server'],
                    'port': int(item['port'])
                }

                # 根据不同类型添加特定字段
                if node_type == 'ss':
                    node['cipher'] = item.get('cipher', 'aes-256-gcm')
                    node['password'] = item.get('password', '')
                elif node_type == 'vmess':
                    node['uuid'] = item.get('uuid', '')
                    node['alterId'] = int(item.get('alterId', 0))
                    node['cipher'] = item.get('cipher', 'auto')
                    node['tls'] = item.get('tls', False)
                    node['network'] = item.get('network', 'tcp')
                    if 'ws-path' in item:
                        node['path'] = item['ws-path']
                elif node_type in ['trojan', 'vless']:
                    node['password'] = item.get('password', '')
                    node['sni'] = item.get('sni', '')

                return node
        except Exception as e:
            logging.info(f"解析Clash节点失败: {str(e)}")
            return None

    return None


def download_xray_core():
    """下载Xray核心程序到当前目录"""
    logging.info("正在自动下载Xray核心程序...")

    # 检测操作系统类型
    is_windows = platform.system() == "Windows"
    is_64bit = platform.architecture()[0] == '64bit'

    # 获取最新版本的Xray发布信息
    try:
        api_url = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
        response = requests.get(api_url, timeout=30)
        release_info = response.json()

        # 确定下载文件名
        if is_windows:
            if is_64bit:
                file_keyword = "windows-64"
            else:
                file_keyword = "windows-32"
        else:  # Linux
            if is_64bit:
                file_keyword = "linux-64"
            else:
                file_keyword = "linux-32"

        # 查找匹配的下载URL
        download_url = None
        for asset in release_info['assets']:
            if file_keyword in asset['name'].lower() and asset['name'].endswith('.zip'):
                download_url = asset['browser_download_url']
                break

        if not download_url:
            logging.info(f"未找到适合当前平台({file_keyword})的Xray下载链接")
            return False

        # 下载Xray
        logging.info(f"下载Xray: https://ghproxy.net/{download_url}")
        download_response = requests.get(f"https://ghproxy.net/{download_url}", timeout=120)
        download_response.raise_for_status()

        # 创建目录结构
        xray_dir = "./xray-core"
        platform_dir = os.path.join(xray_dir, "windows-64" if is_windows else "linux-64")
        os.makedirs(platform_dir, exist_ok=True)

        # 解压缩文件
        with zipfile.ZipFile(io.BytesIO(download_response.content)) as z:
            z.extractall(platform_dir)

        # 设置执行权限（Linux）
        if not is_windows:
            xray_path = os.path.join(platform_dir, "xray")
            if os.path.exists(xray_path):
                os.chmod(xray_path, 0o755)

        logging.info(f"Xray核心程序已下载并解压到 {platform_dir}")
        return True

    except Exception as e:
        logging.info(f"下载Xray失败: {str(e)}")
        return False


def find_core_program():
    """查找V2Ray/Xray核心程序，如果没有找到则自动下载Xray"""
    global CORE_PATH

    # 检测操作系统类型
    is_windows = platform.system() == "Windows"

    # V2Ray可执行文件名
    v2ray_exe = "v2ray.exe" if is_windows else "v2ray"
    xray_exe = "xray.exe" if is_windows else "xray"

    # 首先检查xray-core目录
    xray_core_dir = "./xray-core"
    platform_dir = "windows-64" if is_windows else "linux-64"
    xray_platform_path = os.path.join(xray_core_dir, platform_dir, xray_exe)

    # 检查Xray是否存在
    if os.path.isfile(xray_platform_path) and os.access(xray_platform_path, os.X_OK if not is_windows else os.F_OK):
        CORE_PATH = xray_platform_path
        logging.info(f"找到Xray核心程序: {CORE_PATH}")
        return CORE_PATH

    # 然后检查v2ray-core目录
    v2ray_core_dir = "./v2ray-core"
    v2ray_platform_path = os.path.join(v2ray_core_dir, platform_dir, v2ray_exe)

    # 检查V2Ray是否存在
    if os.path.isfile(v2ray_platform_path) and os.access(v2ray_platform_path, os.X_OK if not is_windows else os.F_OK):
        CORE_PATH = v2ray_platform_path
        logging.info(f"找到V2Ray核心程序: {CORE_PATH}")
        return CORE_PATH

    # 搜索路径
    search_paths = [
        ".",  # 当前目录
        "./v2ray",  # v2ray子目录
        "./xray",  # xray子目录
        os.path.expanduser("~"),  # 用户主目录
    ]

    # Windows特定搜索路径
    if is_windows:
        search_paths.extend([
            "C:\\Program Files\\v2ray",
            "C:\\Program Files (x86)\\v2ray",
            "C:\\v2ray",
        ])
    # Linux特定搜索路径
    else:
        search_paths.extend([
            "/usr/bin",
            "/usr/local/bin",
            "/opt/v2ray",
            "/opt/xray",
        ])

    # 搜索V2Ray或XRay可执行文件
    for path in search_paths:
        v2ray_path = os.path.join(path, v2ray_exe)
        xray_path = os.path.join(path, xray_exe)

        if os.path.isfile(v2ray_path) and os.access(v2ray_path, os.X_OK if not is_windows else os.F_OK):
            CORE_PATH = v2ray_path
            logging.info(f"找到V2Ray核心程序: {CORE_PATH}")
            return CORE_PATH

        if os.path.isfile(xray_path) and os.access(xray_path, os.X_OK if not is_windows else os.F_OK):
            CORE_PATH = xray_path
            logging.info(f"找到XRay核心程序: {CORE_PATH}")
            return CORE_PATH

    # 如果未找到核心程序，自动下载Xray
    logging.info("未找到V2Ray或Xray核心程序，准备自动下载...")
    if download_xray_core():
        # 重新检查Xray是否已下载
        if os.path.isfile(xray_platform_path) and os.access(xray_platform_path, os.X_OK if not is_windows else os.F_OK):
            CORE_PATH = xray_platform_path
            logging.info(f"已成功下载并使用Xray核心程序: {CORE_PATH}")
            return CORE_PATH

    # 如果仍未找到，提示用户手动下载
    logging.info("自动下载失败。请访问 https://github.com/XTLS/Xray-core/releases 手动下载并安装")
    logging.info("将Xray核心程序放在当前目录或指定系统路径中")
    return None


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
        start_time = time.time()

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
                    latency = int((time.time() - start_time) * 1000)
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


def _test_latency(node):
    """测试节点延迟"""
    # 必须有核心程序才能进行测试
    if not CORE_PATH:
        logging.info(f"未找到核心程序，无法测试节点: {node['name']}")
        return -1

    # 使用核心程序进行精确测试
    latency = _test_node_latency(node)

    return latency


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





def load_subscriptions(config: dict) -> list[str]:
    """加载并合并配置中的订阅链接和汇聚订阅链接，去重后返回列表。"""
    subs = config.get("subscriptions", [])
    agg_url = config.get("aggSubs")

    if agg_url:
        resp = requests.get(agg_url, timeout=10)
        if resp.ok:
            subs.extend(resp.text.splitlines())

    # 去重且保持顺序
    return list(dict.fromkeys(subs))


def _fetch_and_extract(link: str) -> list[dict]:
    """
    线程中运行：拉取订阅、提取节点列表。
    返回一个节点字典列表，失败时返回空列表。
    """
    try:
        with requests.Session() as session:
            resp = session.get(link, timeout=10)
            resp.raise_for_status()
            nodes = extract_nodes(resp.text)
            logging.info(f"  ✓ 完成：{link}，提取 {len(nodes)} 个节点")
            return nodes
    except Exception as e:
        logging.warning(f"[WARN] 拉取/解析失败：{link} -> {e}")
        return []


@timer(unit="ms")
def gather_all_nodes(sub_links: list[str], max_workers: int | None = None) -> list[dict]:
    """
    并发拉取并解析所有订阅链接（I/O 密集型），返回聚合后的节点列表。
    """
    max_workers = Settings.THREAD_POOL_SIZE if max_workers is None else max_workers
    logging.info(f"开始并发获取节点信息，使用线程池最大并发数：{max_workers}")
    all_nodes: list[dict] = []

    # 不指定 max_workers 时，ThreadPoolExecutor 会使用 min(32, os.cpu_count() + 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_link = {executor.submit(_fetch_and_extract, link): link for link in sub_links}
        for future in as_completed(future_to_link):
            # 即使 _fetch_and_extract 已经捕获了异常，这里也做一层保险
            try:
                nodes = future.result()
                all_nodes.extend(nodes)
            except Exception as e:
                link = future_to_link[future]
                logging.error(f"[ERROR] 处理 {link} 的线程异常：{e}")

    logging.info(f"全部完成，总计提取节点：{len(all_nodes)}")
    return all_nodes


@timer(unit="ms")
def _test_all_nodes_latency(
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


def init():
    """初始化设置和日志记录"""
    Settings.setup()
    Logger.init(
        level=logging.INFO,
        log_file=f"logs/app_{utils.iso_date_dd}.log",
        max_bytes=10_000_000,
        backup_count=5,
        console=True,
        colored=True
    )
    logging.info("应用初始化完成")


def main():
    # 应用初始化
    init()
    """主函数，执行所有步骤"""
    config = Settings().config
    core_path = find_core_program()
    logging.info(f"核心程序路径：{core_path}")

    # 1. 加载并去重订阅
    sub_links = load_subscriptions(config)
    logging.info(f"共 {len(sub_links)} 条订阅链接")

    # 2. 获取并解析所有节点
    all_nodes = gather_all_nodes(sub_links)
    logging.info(f"提取到节点总数：{len(all_nodes)}")

    # 3. 去重
    unique_nodes = utils.deduplicate_v2ray_nodes(all_nodes)
    logging.info(f"去重后节点数量：{len(unique_nodes)}")

    # 4. 测试延迟
    valid_nodes = _test_all_nodes_latency(unique_nodes, 100)
    logging.info(f"有效节点数量：{len(valid_nodes)}")

    # 5. 保存结果
    utils.save_results(valid_nodes, "v2ray.txt")


if __name__ == "__main__":
    main()
