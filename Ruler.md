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

## 安粮期货程序化接入（对照 TqSdk）

- 本地协议目录：项目下「安粮期货」文件夹（含外部系统接入申请表/承诺书/风险提示书）
- 走天勤中继（推荐，代码用 `TqAccount("A安粮期货", ...)`）时：
  - AppID / RelayAPPID：`SHINNY_TQ_1.0`
  - 外接系统名称：天勤量化（TqSdk）
  - 版本号：当前已装 `tqsdk` 版本（如 `3.10.1`）
  - 对接系统：CTP
  - 终端类型：中继（多对多），中继归属：信易科技 / 天勤
- 安粮在天勤「专业版可用」列表；实盘需专业版 + 公司侧 AppID 绑定 / 白名单
- 代码示例：`TqApi(TqAccount("A安粮期货", "资金账号", "密码"), auth=TqAuth(...))`

## 策略回测

### 回测 Web UI 固定地址（全局约定）

- 所有带界面的回测统一固定：`web_gui=":9876"`
- 浏览器访问域名/地址固定为：**http://127.0.0.1:9876**
- 不要用 `web_gui=True`（会随机端口，地址不稳定）
- 若 9876 被占用：先结束旧回测进程，再启动新回测

### 现有策略

- 沪金 VWAP：`strategies/vwap_au_backtest.py`
  - 合约默认 `SHFE.au2606`，区间 `2026-01-01` ~ `2026-05-31`
  - Web UI：http://127.0.0.1:9876
  - 凭证读 `.env`；运行：`python strategies/vwap_au_backtest.py`
