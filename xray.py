import io
import logging
import os
import platform
import zipfile
import requests


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
