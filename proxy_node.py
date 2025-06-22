import base64
import json
import logging
import re
from typing import List, Dict, Any, Optional
from common.constants import SUPPORTED_PROTOCOLS
from parser import parse_json_nodes, parse_v2ray_uri, parse_clash_yaml


def extract_nodes(content: str) -> List[Dict[str, Any]]:
    """按优先级 Base64 → YAML → 正则 → JSON 提取代理节点，一旦成功即返回结果。"""
    if not content:
        logging.info("内容为空，跳过提取")
        return []

    # 1. Base64 解码提取
    b64 = re.sub(r'[^A-Za-z0-9+/=]', '', content)
    padding = len(b64) % 4
    if padding:
        b64 += '=' * (4 - padding)
    try:
        decoded = base64.b64decode(b64, validate=True).decode('utf-8', 'ignore')
        if any(proto in decoded for proto in SUPPORTED_PROTOCOLS):
            nodes = _extract_from_lines(decoded.splitlines())
            if nodes:
                logging.info(f"通过 Base64 提取到 {len(nodes)} 个节点")
                return nodes
    except Exception:
        pass

    # 2. YAML 提取（Clash 格式）
    yaml_text = re.sub(r'<[^>]+>|!&lt;str&gt;', '', content)
    yaml_keys = ('proxies:', 'proxy-providers:', 'type: vmess', 'type: ss',
                 'type: trojan', 'type: vless')
    if any(key in yaml_text for key in yaml_keys):
        try:
            nodes = parse_clash_yaml(yaml_text)
            if nodes:
                logging.info(f"通过 YAML 提取到 {len(nodes)} 个节点")
                return nodes
        except Exception:
            # 尝试提取 proxies 块
            m = re.search(r'proxies:\s*\n([\s\S]+?)(?=\n\S+:|$)', yaml_text)
            if m:
                try:
                    nodes = parse_clash_yaml("proxies:\n" + m.group(1))
                    if nodes:
                        logging.info(f"通过 YAML(proxies 块) 提取到 {len(nodes)} 个节点")
                        return nodes
                except Exception:
                    pass

    # 3. 正则 URI 提取
    for proto in SUPPORTED_PROTOCOLS:
        pattern = (
            r'vmess://[A-Za-z0-9+/=]+' if proto == 'vmess://'
            else re.escape(proto) + r'[^"\'<>\s]+'
        )
        matches = re.findall(pattern, content)
        if matches:
            nodes = [_parse_uri(uri) for uri in matches]
            nodes = [n for n in nodes if n]
            if nodes:
                logging.info(f"通过 正则({proto}) 提取到 {len(nodes)} 个节点")
                return nodes

    # 4. JSON 提取
    cleaned = re.sub(r'<[^>]+>|/\*.*?\*/|//.*?$', '', content, flags=re.MULTILINE)
    try:
        data = json.loads(cleaned)
        nodes = parse_json_nodes(data)
        if nodes:
            logging.info(f"通过 JSON 提取到 {len(nodes)} 个节点")
            return nodes
    except Exception:
        # 尝试提取 JSON 片段
        for snippet in re.findall(r'(\{[\s\S]*?\}|\[[\s\S]*?\])', cleaned):
            try:
                data = json.loads(snippet)
                nodes = parse_json_nodes(data)
                if nodes:
                    logging.info(f"通过 JSON 片段提取到 {len(nodes)} 个节点")
                    return nodes
            except Exception:
                continue

    logging.info("未找到任何节点")
    return []


def _extract_from_lines(lines: List[str]) -> List[Dict[str, Any]]:
    """从每行 URI 中 parse 出节点。"""
    result = []
    for line in lines:
        line = line.strip()
        if any(line.startswith(proto) for proto in SUPPORTED_PROTOCOLS):
            node = parse_v2ray_uri(line)
            if node:
                result.append(node)
    return result


def _parse_uri(uri: str) -> Optional[Dict[str, Any]]:
    """统一调用 parse_v2ray_uri，捕获异常。"""
    try:
        return parse_v2ray_uri(uri)
    except Exception:
        return None


class ProxyNodeExtractor:
    @staticmethod
    def extract_proxy_nodes(text: str) -> List[Dict[str, Any]]:
        return extract_nodes(text)
