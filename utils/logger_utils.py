import sys
import os
from datetime import datetime

class DualLogger(object):
    """同时输出到控制台和日志文件"""
    def __init__(self, filename):
        self.terminal = sys.__stdout__
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        pass


def enable_console_to_log(log_dir=r"results\logs", prefix="log"):
    """
    启动 print() → 控制台 + 日志文件 的重定向功能
    只需要在主入口调用一次即可生效
    """

    # 创建目录
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(
        log_dir,
        f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.txt"
    )

    # 启动双输出 logger
    sys.stdout = DualLogger(log_file)
    sys.stderr = DualLogger(log_file)

    print(f"日志记录启动，文件位于：{log_file}\n")
