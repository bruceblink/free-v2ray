import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config.settings import Settings
from proxy_node import ProxyNodeExtractor


class Subscriber:
    def __init__(self, config: dict):
        self.config: dict = config

    def get_subscription_url(self) -> list[str]:
        """获取订阅链接列表"""
        """加载并合并配置中的订阅链接和汇聚订阅链接，去重后返回列表。"""
        subs = self.config.get("subscriptions", [])
        agg_url = self.config.get("aggSubs")

        if agg_url:
            resp = requests.get(agg_url, timeout=10)
            if resp.ok:
                subs.extend(resp.text.splitlines())
        # 去重且保持顺序
        return list(dict.fromkeys(subs))

    def get_subscription_nodes(self, max_workers: int | None = None) -> list[dict]:
        """获取订阅节点列表"""
        max_workers = Settings.THREAD_POOL_SIZE if max_workers is None else max_workers
        logging.info(f"开始并发获取节点信息，使用线程池最大并发数：{max_workers}")
        all_nodes: list[dict] = []
        sub_links = self.get_subscription_url()
        logging.info(f"共 {len(sub_links)} 条订阅链接")
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


def _fetch_and_extract(link: str) -> list[dict]:
    """
    线程中运行：拉取订阅、提取节点列表。
    返回一个节点字典列表，失败时返回空列表。
    """
    try:
        with requests.Session() as session:
            resp = session.get(link, timeout=10)
            resp.raise_for_status()
            nodes = ProxyNodeExtractor.extract_proxy_nodes(resp.text)
            logging.info(f"  ✓ 完成：{link}，提取 {len(nodes)} 个节点")
            return nodes
    except Exception as e:
        logging.warning(f"[WARN] 拉取/解析失败：{link} -> {e}")
        return []



