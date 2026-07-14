"""验证 tqsdk 是否安装成功，并订阅一手行情做连通性检查。

账号密码从环境变量或项目根目录 .env 读取（勿把真实密码写入本文件或提交到 Git）。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main() -> int:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")

    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        print("缺少账号密码。请在项目根目录创建 .env，内容示例：")
        print("  TQ_USER=你的快期账户")
        print("  TQ_PASS=你的账户密码")
        return 1

    try:
        from tqsdk import TqApi, TqAuth
    except ImportError:
        print("未安装 tqsdk。请先执行：")
        print(
            "  pip install tqsdk -U -i https://pypi.tuna.tsinghua.edu.cn/simple "
            "--trusted-host=pypi.tuna.tsinghua.edu.cn"
        )
        return 1

    symbol = os.environ.get("TQ_SYMBOL", "SHFE.ni2607").strip()
    max_updates = int(os.environ.get("TQ_VERIFY_UPDATES", "5"))
    timeout_sec = float(os.environ.get("TQ_VERIFY_TIMEOUT", "15"))

    print(f"tqsdk 已导入，正在连接行情: {symbol}")
    api = TqApi(auth=TqAuth(user, password))
    try:
        quote = api.get_quote(symbol)
        got = 0
        deadline = time.time() + timeout_sec
        while got < max_updates and time.time() < deadline:
            updated = api.wait_update(deadline=deadline)
            # 盘后可能长时间没有推送；只要 quote 有字段就打印并计为成功探测
            if quote.datetime or quote.last_price is not None:
                got += 1
                print(f"[{got}/{max_updates}] {quote.datetime}  last_price={quote.last_price}")
                if not updated:
                    break
            elif not updated:
                break

        if got == 0:
            print("已连接，但在超时时间内未收到行情（可能非交易时段或合约已到期）。")
            print(f"当前 quote.datetime={quote.datetime!r}, last_price={quote.last_price!r}")
            print("tqsdk 安装本身正常；请换主力合约或交易时段再试。")
            return 0

        print("安装与连通性验证通过。")
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    sys.exit(main())
