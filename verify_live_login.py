"""仅登录银河期货实盘并打印账户资金（不下单）。

凭证从项目根目录 .env 读取，勿把密码写入代码或提交到 Git。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")

    auth_user = os.environ.get("TQ_USER", "").strip()
    auth_pass = os.environ.get("TQ_PASS", "").strip()
    broker = os.environ.get("TQ_BROKER", "Y银河期货").strip()
    account_id = os.environ.get("TQ_FUTURE_ACCOUNT", "").strip()
    account_pass = os.environ.get("TQ_FUTURE_PASSWORD", "").strip()

    if not all([auth_user, auth_pass, account_id, account_pass]):
        print("缺少登录配置。请在 .env 中设置：")
        print("  TQ_USER / TQ_PASS / TQ_BROKER / TQ_FUTURE_ACCOUNT / TQ_FUTURE_PASSWORD")
        return 1

    from tqsdk import TqAccount, TqApi, TqAuth

    print(f"尝试登录: broker={broker}, account={account_id}")
    try:
        from tqsdk.exceptions import TqTimeoutError

        api = TqApi(
            TqAccount(broker, account_id, account_pass),
            auth=TqAuth(auth_user, auth_pass),
        )
    except TqTimeoutError as exc:
        print(f"登录超时: {exc}")
        print(
            "常见原因：期货公司尚未把该资金账号加入天勤中继白名单 / 未完成穿透式认证绑定"
            "（AppID: SHINNY_TQ_1.0）。请联系银河销售处理后再跑本脚本。"
        )
        return 2

    try:
        account = api.get_account()
        api.wait_update(deadline=__import__("time").time() + 15)
        print(
            "登录成功 | "
            f"权益={account.balance} 可用={account.available} "
            f"保证金={account.margin} 风险度={account.risk_ratio}"
        )
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    sys.exit(main())
