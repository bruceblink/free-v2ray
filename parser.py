import base64
import json
import logging
from urllib.parse import parse_qs, urlparse, unquote
import yaml
from common.constants import DEBUG_MODE


def node_to_v2ray_uri(node: dict) -> str | None:
    """将节点信息转换为V2Ray URI格式"""
    if node['type'] == 'vmess':
        config = {
            'v': '2',
            'ps': node['name'],
            'add': node['server'],
            'port': str(node['port']),
            'id': node['uuid'],
            'aid': str(node['alterId']),
            'net': node.get('network', 'tcp'),
            'type': node.get('type', 'none'),
            'tls': 'tls' if node.get('tls', False) else ''
        }
        return f"vmess://{base64.b64encode(json.dumps(config).encode()).decode()}"
    elif node['type'] == 'trojan':
        return f"trojan://{node['password']}@{node['server']}:{node['port']}?sni={node['name']}"
    elif node['type'] == 'vless':
        # 构建vless uri
        query_parts = []
        if node.get('tls'):
            query_parts.append('security=tls')
        if node.get('flow'):
            query_parts.append(f"flow={node['flow']}")
        if node.get('network'):
            query_parts.append(f"type={node['network']}")
        query_string = '&'.join(query_parts)
        return f"vless://{node['uuid']}@{node['server']}:{node['port']}?{query_string}&remarks={node['name']}"
    elif node['type'] == 'ss':
        # 构建ss uri
        userinfo = f"{node['cipher']}:{node['password']}"
        b64_userinfo = base64.b64encode(userinfo.encode()).decode()
        return f"ss://{b64_userinfo}@{node['server']}:{node['port']}#{node['name']}"
    elif node['type'] == 'ssr':
        # 构建ssr uri
        password_b64 = base64.b64encode(node['password'].encode()).decode()
        name_b64 = base64.b64encode(node['name'].encode()).decode()
        ssr_str = f"{node['server']}:{node['port']}:{node['protocol']}:{node['cipher']}:{node['obfs']}:{password_b64}/?remarks={name_b64}"
        return f"ssr://{base64.b64encode(ssr_str.encode()).decode()}"
    elif node['type'] in ['http', 'https']:
        # 构建http/https uri
        proto = 'http' if node['type'] == 'http' else 'https'
        auth = f"{node.get('username', '')}:{node.get('password', '')}@ {node.get('username', '')}"
        return f"{proto}://{auth}{node['server']}:{node['port']}?remarks={node['name']}"
    elif node['type'] == 'socks':
        # 构建socks uri
        auth = f"{node.get('username', '')}:{node.get('password', '')}@ {node.get('username')}"
        return f"socks://{auth}{node['server']}:{node['port']}?remarks={node['name']}"
    elif node['type'] == 'hysteria':
        # 构建hysteria uri
        auth = f"{node['auth']}@" if node.get('auth') else ""
        protocol_part = f"?protocol={node['protocol']}" if node.get('protocol') else ""
        return f"hysteria://{auth}{node['server']}:{node['port']}{protocol_part}&peer={node['name']}"
    elif node['type'] == 'wireguard':
        # 构建wireguard uri
        query_parts = []
        if node.get('private_key'):
            query_parts.append(f"privateKey={node['private_key']}")
        if node.get('public_key'):
            query_parts.append(f"publicKey={node['public_key']}")
        if node.get('allowed_ips'):
            query_parts.append(f"allowedIPs={node['allowed_ips']}")
        query_string = '&'.join(query_parts)
        return f"wireguard://{node['server']}:{node['port']}?{query_string}&remarks={node['name']}"
    return None


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
