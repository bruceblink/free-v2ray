import base64
import io
import logging
import os
import platform
import re
import zipfile
from datetime import datetime
import requests
from common.logger import Logger
from config.settings import Settings
from subscription import Subscriber
from tester import test_all_nodes_latency
from utils import utils


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
    subscriber = Subscriber(config)

    # 2. 获取并解析所有节点
    all_nodes = subscriber.get_subscription_nodes()
    logging.info(f"提取到节点总数：{len(all_nodes)}")

    # 3. 去重
    unique_nodes = utils.deduplicate_v2ray_nodes(all_nodes)
    logging.info(f"去重后节点数量：{len(unique_nodes)}")

    # 4. 测试延迟
    valid_nodes = test_all_nodes_latency(unique_nodes, 100)
    logging.info(f"有效节点数量：{len(valid_nodes)}")

    # 5. 保存结果
    utils.save_results(valid_nodes, "v2ray.txt")


if __name__ == "__main__":
    main()
