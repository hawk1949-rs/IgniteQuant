# IgniteQuant 开发指引

## GitHub

- 个人仓库：https://github.com/hawk1949-rs/IgniteQuant
- 账号：`hawk1949-rs`
- 可见性：Public
- 本地目录已 `git init`，远程为 `origin` → `https://github.com/hawk1949-rs/IgniteQuant.git`
- 已添加 `README.md` 并完成首次提交推送

## Python / 依赖

- Python：`3.10.11`
- 天勤量化框架：`tqsdk`（清华镜像安装）
  - 安装命令：`pip install tqsdk -U -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host=pypi.tuna.tsinghua.edu.cn`
  - 或：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host=pypi.tuna.tsinghua.edu.cn`
- 依赖清单：`requirements.txt`
- 安装连通性校验脚本：`verify_install.py`
  - 凭证放在本地 `.env`（已在 `.gitignore`，仓库为 Public，禁止把密码写进代码）
  - 可参考 `.env.example`
  - 运行：`python verify_install.py`
  - 默认订阅 `SHFE.ni2607`，最多打印 5 次行情；可用 `TQ_SYMBOL`、`TQ_VERIFY_UPDATES`、`TQ_VERIFY_TIMEOUT` 调整
  - 本地 `.env` 已放账户信息；提交前确认未被 `git add`（依赖 `.gitignore`）

## 期货公司对接

### 银河期货（当前主推实盘渠道）

- 状态：资金账号已开好；席位 **CTP主席**；凭证只写本地 `.env`（`TQ_BROKER` / `TQ_FUTURE_ACCOUNT` / `TQ_FUTURE_PASSWORD`），**禁止提交 Git**
- 天勤公司名（中继）：`Y银河期货`（主席）；若登录异常再问销售是否要换七席/三席名
- 2026-07-15 登录自检：连上 `kqzj.yhqh.com.cn` 后提示需期货公司做**穿透式认证/白名单**，否则 TqSdk 无法完成实盘登录（非密码错误）
- 待销售处理：把资金账号加入天勤中继白名单，并绑定 AppID `SHINNY_TQ_1.0`
- 走天勤中继填表常用值：外接系统天勤量化（TqSdk），对接 CTP，终端类型中继（多对多），归属信易科技
- 登录自检（只查资金、不下单）：`python verify_live_login.py`
- 代码形态：

```python
api = TqApi(
    TqAccount("Y银河期货", os.environ["TQ_FUTURE_ACCOUNT"], os.environ["TQ_FUTURE_PASSWORD"]),
    auth=TqAuth(os.environ["TQ_USER"], os.environ["TQ_PASS"]),
)
```

### 安粮期货（早期资料，非当前主渠道）

- 本地「安粮期货」协议文件已移除（含实名填表信息，不再入库）
- 中继写法：`TqAccount("A安粮期货", ...)`；AppID：`SHINNY_TQ_1.0`
- 安粮在天勤「专业版可用」列表

## 策略回测

### 回测 Web UI 固定地址（全局约定）

- 所有带界面的回测统一固定：`web_gui=":9876"`
- 浏览器访问域名/地址固定为：**http://127.0.0.1:9876**
- 不要用 `web_gui=True`（会随机端口，地址不稳定）
- 若 9876 被占用：先结束旧回测进程，再启动新回测
- web_gui 常停在「最后一笔成交」：后台可能已继续推进或已 `BacktestFinished`；无新信号时图表不再跳动，属正常

### 现有策略

- 沪金 VWAP：`strategies/vwap_au_backtest.py`
  - 合约默认 `SHFE.au2606`，区间 `2026-01-01` ~ `2026-05-31`
  - Web UI：http://127.0.0.1:9876
  - 凭证读 `.env`；运行：`python strategies/vwap_au_backtest.py`
- Falcon（格兰维尔均线）：`strategies/falcon_au_backtest.py`
  - 均线：`MA7 / MA14 / MA52`（1 小时 K）；主均线 MA52，短中期 MA7/MA14 确认
  - 合约与区间同 VWAP：`SHFE.au2606`，`2026-01-01` ~ `2026-05-31`
  - 结束日前最后一个交易日起强制 `set_target_volume(0)` 清仓
  - Web UI：http://127.0.0.1:9876
  - 运行：`python strategies/falcon_au_backtest.py`
