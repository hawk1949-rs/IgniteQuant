# 免费访问：用公网 IP（不买域名）

域名 `ignitequant.com` **不是必须的**。家里宽带 + 端口转发即可，不额外花钱。

## 地址（当前）

先查公网 IP：

```powershell
Invoke-RestMethod https://api.ipify.org
```

然后打开（把 IP 换成查到的）：

```text
http://公网IP/#/sim
```

或直连容器端口：

```text
http://公网IP:8787/#/sim
```

本机：`http://127.0.0.1:8787/#/sim`

## 路由器（只需一次）

把外网 **TCP 80**（以及可选 **8787**）转发到本机局域网 IP（如 `192.168.1.56`）。

Windows 防火墙已放行 80；8787 若外网直连也请放行。

## 启动

```powershell
cd D:\Cursor\IGNITE\AIQuant\deploy\cockpit
docker compose up -d
```

> 家宽 IP 可能会变；变了就换新数字地址。不需要为座舱单独买域名。
