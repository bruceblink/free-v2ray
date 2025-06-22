from tqdm import tqdm
import time


if __name__ == '__main__':
    # 直接使用tqdm包装一个可迭代对象
    for i in tqdm(range(100), desc="Processing"):
        time.sleep(0.01)  # 模拟任务