class TesterAdapter:
    """
    tester适配器类，用于适配不同的测试器实现,例如v2ray, xray等。
    """

    def __init__(self, install_path: str) -> None:
        self.install_path = install_path

    def get_download_url(self) -> str | None:
        """获取适配器的下载链接。"""
        pass

    def install_adapter(self, timeout: int = 10) -> str:
        """ 安装适配器。"""
        pass

    def start_adapter(self) -> None:
        """
        启动适配器。
        """
        pass
