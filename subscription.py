import asyncio
import logging
from typing import List, Dict, Optional
import aiohttp
from common.decorators import timer
from config.settings import Settings
from proxy_node import ProxyNodeExtractor


async def _fetch_and_extract(session: aiohttp.ClientSession, url: str) -> List[Dict]:
    try:
        async with session.get(url, timeout=10) as resp:
            resp.raise_for_status()
            text = await resp.text()
        nodes = ProxyNodeExtractor.extract_proxy_nodes(text)
        logging.info(f"  ✓ 完成：{url}，提取 {len(nodes)} 个节点")
        return nodes
    except Exception as e:
        logging.warning(f"[WARN] 拉取/解析失败：{url} -> {e}")
        return []


class Subscriber:
    def __init__(self, config: Dict):
        self.config = config
        # 限制并发请求数，避免过快发送
        self._sem = asyncio.Semaphore(50)  # 最多同时 50 个请求

    async def get_subscription_url(self) -> List[str]:
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
        return list(dict.fromkeys(subs))

    @timer(unit="ms")
    async def get_subscription_nodes(self) -> List[Dict]:
        urls = await self.get_subscription_url()
        logging.info(f"共 {len(urls)} 条订阅链接，开始并发提取节点（限 {Settings.THREAD_POOL_SIZE} 并发）")

        all_nodes: List[Dict] = []
        async with aiohttp.ClientSession() as session:
            tasks = []
            for url in urls:
                # 在启动任务前获取 semaphore，保证同时只有 N 个正在进行请求
                await self._sem.acquire()
                task = asyncio.create_task(_fetch_and_extract(session, url))
                # 请求完成后释放 semaphore
                task.add_done_callback(lambda t: self._sem.release())
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

        for url, res in zip(urls, results):
            if isinstance(res, Exception):
                logging.error(f"[ERROR] 处理 {url} 异常：{res!r}")
            else:
                all_nodes.extend(res)

        logging.info(f"全部完成，总计提取节点：{len(all_nodes)}")
        return all_nodes

# 用法示例
# import asyncio, json
# cfg = json.load(open("config.json"))
# subscriber = Subscriber(cfg)
# nodes = asyncio.run(subscriber.get_subscription_nodes())
