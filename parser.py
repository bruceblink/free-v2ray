import base64
import json


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
        auth = f"{node['username']}:{node['password']}@" if node['username'] else ""
        return f"{proto}://{auth}{node['server']}:{node['port']}?remarks={node['name']}"
    elif node['type'] == 'socks':
        # 构建socks uri
        auth = f"{node['username']}:{node['password']}@" if node['username'] else ""
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