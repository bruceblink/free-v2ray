import base64
import json
import logging
import re

from common.constants import SUPPORTED_PROTOCOLS
from parser import parse_json_nodes, parse_v2ray_uri, parse_clash_yaml


class ProxyNodeExtractor:
    @staticmethod
    def extract_proxy_nodes(resp_text: str) -> list[dict]:
        return extract_nodes(resp_text)


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