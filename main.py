import asyncio
import logging

from common.decorators import timer
from common.logger import Logger
from config.settings import Settings
from subscription import Subscriber, AsyncSubscriber
from tester import Tester, AsyncTester, XrayOrV2RayBooster
from utils import utils


def init():
    """初始化设置和日志记录"""
    Settings.setup()
    Logger.init(
        level=logging.INFO,
        log_file=f"logs/app_{utils.iso_date_dd}.log",
        max_bytes=10_000_000,
        backup_count=5,
        console=True,
        colored=True
    )
    logging.info("应用初始化完成")


@timer(unit="ms")
def main():
    # 应用初始化
    init()
    """主函数，执行所有步骤"""
    xray_booster = XrayOrV2RayBooster()
    xray_download_url = xray_booster.get_xray_download_url()
    if not xray_booster.install_xray_core(xray_download_url):
        logging.error("未找到V2Ray或Xray核心程序，请手动下载并放置在当前目录或系统路径中")
        raise EnvironmentError("xray测试核心程序安装失败")
    # 1. 初始化订阅者
    subscriber = Subscriber(Settings().config)
    # subscriber = AsyncSubscriber(config)

    # 2. 获取并解析所有节点
    # all_nodes = asyncio.run(subscriber.get_subscription_nodes())
    all_nodes = subscriber.get_subscription_nodes()
    logging.info(f"提取到节点总数：{len(all_nodes)}")

    # 3. 去重
    unique_nodes = utils.deduplicate_v2ray_nodes(all_nodes)
    logging.info(f"去重后节点数量：{len(unique_nodes)}")
    utils.save_results(unique_nodes, "v2ray_raw.txt")
    # 4. 测试延迟
    # 构造测试器
    """
    tester = Tester(xray_booster)
    valid_nodes = tester.test_all_nodes_latency(unique_nodes, 100)
    """

    async_tester = AsyncTester(xray_booster)
    valid_nodes = asyncio.run(async_tester.test_all_nodes_latency(unique_nodes, 100))

    logging.info(f"有效节点数量：{len(valid_nodes)}")

    # 5. 保存测试后的结果
    utils.save_results(valid_nodes, "v2ray.txt")


if __name__ == "__main__":
    main()
