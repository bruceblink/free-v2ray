import base64
import logging
import re
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from config.settings import Settings
from parser import node_to_v2ray_uri

now = datetime.now()

# 常见格式示例
iso_date = now.strftime("%Y-%m-%d")  # 2025-06-17
iso_date_dd = now.strftime("%Y_%m_%d")  # 2025_06_17
iso_date_ld = now.strftime("%Y/%m/%d")  # 2025/06/17
iso_datetime = now.strftime("%Y-%m-%d %H:%M:%S")  # 2025-06-17 10:23:45
chinese_date = now.strftime("%Y年%m月%d日")  # 2025年06月17日
compact = now.strftime("%y%m%d")  # 250617
weekday = now.strftime("%A")  # Tuesday
weekday_today = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]


def save_results(nodes: list[dict], file_name) -> None:
    """将节点列表转为 V2Ray URI，保存为 base64 和原始文本。"""
    if not nodes:
        logging.info("未找到有效节点，不生成文件")
        return
    # 优化为海象运算符 只调用一次 node_to_v2ray_uri
    uris = [uri for n in nodes if (uri := node_to_v2ray_uri(n))]
    raw = "\n".join(uris)
    b64 = base64.b64encode(raw.encode()).decode()
    v2ray_txt = Settings.V2RAY_DIR / file_name
    v2ray_txt.write_text(b64, encoding="utf-8")
    logging.info(f"已保存 {len(uris)} 条节点（base64）到 {v2ray_txt}")

    v2ray_txt.write_text(raw, encoding="utf-8")
    logging.info(f"已保存原始文本到 {v2ray_txt}")


def deduplicate_v2ray_nodes(nodes):
    """根据节点唯一属性去重，例如用 server:port。"""
    seen = set()
    unique = []
    for node in nodes:
        key = f"{node['server']}:{node['port']}"
        if key and key not in seen:
            seen.add(key)
            unique.append(node)
    return unique


def is_github_raw_url(url):
    """判断是否为GitHub的raw URL"""
    return 'raw.githubusercontent.com' in url


def extract_file_pattern(url):
    """从URL中提取文件模式，例如{x}.yaml中的.yaml"""
    match = re.search(r'\{x}(\.[a-zA-Z0-9]+)(?:/|$)', url)
    if match:
        return match.group(1)  # 返回文件后缀，如 '.yaml', '.txt', '.json'
    return None


def make_session_with_retries(
        total_retries: int = 5,
        backoff_factor: float = 1.0,
        status_forcelist: tuple = (500, 502, 503, 504),
):
    """构造带 Retry 策略的 requests Session。"""
    session = requests.Session()
    retries = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
