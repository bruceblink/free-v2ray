import asyncio
import logging
from typing import List, Dict, Optional
import aiohttp

from common.decorators import timer
from config.settings import Settings
from proxy_node import ProxyNodeExtractor


class Subscriber:
    def __init__(self, config: Dict):
        self.config = config
        self._sem = asyncio.Semaphore(50)

    async def get_subscription_url(self) -> List[str]:
        """
        获取去重后的订阅链接列表：合并 config 中的 subscriptions 和 aggSubs（若存在）。
        """
        subs = list(self.config.get("subscriptions", []))
        agg_url: Optional[str] = self.config.get("aggSubs")
        if agg_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(agg_url, timeout=10) as resp:
                        resp.raise_for_status()
                        text = await resp.text()
                subs.extend(text.splitlines())
            except Exception as e:
                logging.warning(f"拉取聚合订阅失败：{e}")
        # 去重且保持原始顺序
        return list(dict.fromkeys(subs))

    @timer(unit="ms")
    async def get_subscription_nodes(self) -> List[Dict]:
        """
        异步并发获取所有订阅链接的节点列表，合并后返回。
        并发度受限于 Settings.THREAD_POOL_SIZE。
        """
        urls = await self.get_subscription_url()
        logging.info(f"共 {len(urls)} 条订阅链接，开始并发提取节点")
        tasks = [self._fetch_and_extract(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_nodes: List[Dict] = []
        for url, res in zip(urls, results):
            if isinstance(res, Exception):
                logging.error(f"[ERROR] 处理 {url} 异常：{res!r}")
            else:
                all_nodes.extend(res)
        logging.info(f"全部完成，总计提取节点：{len(all_nodes)}")
        return all_nodes

    async def _fetch_and_extract(self, url: str) -> List[Dict]:
        """
        拉取单个订阅并提取节点。使用信号量限流。
        遇到错误返回空列表。
        """
        async with self._sem:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        resp.raise_for_status()
                        text = await resp.text()
                nodes = ProxyNodeExtractor.extract_proxy_nodes(text)
                logging.info(f"  ✓ 完成：{url}，提取 {len(nodes)} 个节点")
                return nodes
            except Exception as e:
                logging.warning(f"[WARN] 拉取/解析失败：{url} -> {e}")
                return []


# 用法示例
# import asyncio, json
# cfg = json.load(open("config.json"))
# subscriber = Subscriber(cfg)
# nodes = asyncio.run(subscriber.get_subscription_nodes())
