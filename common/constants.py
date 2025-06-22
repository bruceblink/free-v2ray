TIME_OUT_5 = 5  # 超过5秒的耗时
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 "
                  "Safari/537.36 Edg/125.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2"
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Microsoft Edge";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

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