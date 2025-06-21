import asyncio
from random import random


async def worker(name, delay):
    await asyncio.sleep(delay)
    print(f"{name} 完成，耗时 {delay}s")


async def main():
    # 三个任务并发启动
    t1 = asyncio.create_task(worker("任务A", 2))
    t2 = asyncio.create_task(worker("任务B", 1))
    t3 = asyncio.create_task(worker("任务C", 3))

    # 等待所有任务完成
    await asyncio.gather(t1, t2, t3)


async def worker_res(name, delay):
    # 模拟耗时操作
    await asyncio.sleep(delay)
    result = f"{name} 完成，耗时 {delay}s"
    print(result)
    return result  # 把结果返回出去


async def main_res():
    # 三个任务并发启动，注意这里直接把协程对象传给 gather
    tasks = [
        worker_res("任务A", 2),
        worker_res("任务B", 1),
        worker_res("任务C", 3),
    ]

    # await gather 会返回一个 list，包含每个任务的 return 值
    results = await asyncio.gather(*tasks)

    # 在这里你就可以拿到所有任务的返回值
    print("所有任务返回值：")
    for r in results:
        print("  ", r)


sem = asyncio.Semaphore(3)  # 同时最多 3 个并发


async def bound_worker(i):
    async with sem:
        delay = random() * 2
        await asyncio.sleep(delay)
        print(f"工作 {i} 完成（{delay:.2f}s）")


async def main_sem():
    tasks = [asyncio.create_task(bound_worker(i)) for i in range(10)]
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main_res())
    asyncio.run(main_sem())
