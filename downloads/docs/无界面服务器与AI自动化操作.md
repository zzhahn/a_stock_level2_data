# 无界面服务器与 AI 自动化操作

> 这是一份面向云服务器、远程主机、没有桌面环境的长期进程以及 AI Agent 的操作指南。全流程只依赖本机 HTTP 管理 API，不依赖浏览器、桌面环境或人工点击页面。

## 1. 运行模型

客户端启动后有两个本机端口：

```text
AI / 你的业务程序
        │
        ├─ 管理 API：127.0.0.1:9527
        │    查询状态、登录/注册、充值、启动/停止
        │
        └─ 数据 API：127.0.0.1:8080（默认，可由状态返回值改变）
             HTTP / WebSocket 数据接口
```

AI 不需要操控浏览器。推荐把 AI 控制程序和 `data_interface` 放在同一台机器上，并且只访问 `127.0.0.1`。

## 2. AI 应该遵循的固定流程

```text
启动客户端进程
  ↓
GET /api/status，等待管理端返回 JSON
  ↓
POST /api/login（新手机号会自动注册）
  ↓
needRecharge=true 或 isVerified=false？→ POST /api/recharge
  ↓
POST /api/server/start，传入端口
  ↓
GET /api/status，确认 running=true
  ↓
调用已授权的 d1～d6 接口
```

停止时：

- 只停止数据服务：`POST /api/server/stop`；
- 退出整个客户端：`POST /api/exit`；
- 登出：`POST /api/logout`，同时会停止正在运行的数据服务。除非确实要切换账号，不要把登出当作普通停止操作。

不要在登录失败时无限重试。先读取 JSON 中的 `message`、`needRecharge` 和 HTTP 状态，再决定下一步。

## 3. 状态字段与决策规则

调用：

```text
GET http://127.0.0.1:9527/api/status
```

重点字段：

| 字段 | `true` / 有值表示 | AI 下一步 |
|---|---|---|
| `exeConnected` | 管理 API 对应的本机客户端已连接 | 继续读取其他字段 |
| `isLoggedIn` | 当前会话已登录 | 不要重复登录 |
| `isVerified` | 至少有可启动的数据权限 | 可以请求 `/api/server/start` |
| `running` | 数据端正在监听 | 用返回的 `proxyPort` 发业务请求 |
| `proxyPort` | 当前数据端口，默认 `8080` | 所有业务请求都以此值为准 |
| `adminPort` | 管理端口，默认 `9527` | 管理 API 以此值为准 |
| `autostart` | 已设置当前用户的自动启动 | 服务器不要仅依赖此字段，优先使用进程管理器 |
| `openWebOnLaunch` | 启动时尝试打开网页 | 无界面机器应设为 `false` |
| `products` | 各本地产品编号的到期时间 | 只用于展示/诊断，不要把它当作登录 Token |

推荐的状态判断：

```text
exeConnected=false 或没有响应  → 先启动/检查进程和 9527
isLoggedIn=false                → 调用 /api/login
isLoggedIn=true 且 isVerified=false → 需要充值或确认权限
isVerified=true 且 running=false → 调用 /api/server/start
running=true                    → 使用 proxyPort 做数据自测
```

## 4. 管理 API 契约

管理 API 的表单字段和返回 JSON 如下。它不依赖浏览器 Cookie；同一个客户端进程内，AI 按顺序调用这些接口即可。HTTP 状态不是唯一判断依据，尤其是“已登录但未充值”的登录响应；始终解析响应正文。

| 方法 | 路径 | 请求体 | 需要登录 | 用途 |
|---|---|---|:---:|---|
| GET | `/api/status` | 无 | 否 | 查询客户端、会话和端口状态 |
| POST | `/api/login` | `phone`、`password` | 否 | 已有账号登录；新手机号自动注册 |
| POST | `/api/recharge` | `cardKey` | 是 | 激活/续期卡密 |
| POST | `/api/server/start` | `port`，可选 | 是且需有效权限 | 启动数据端 |
| POST | `/api/server/stop` | 无 | 是 | 停止数据端，管理端继续运行 |
| POST | `/api/logout` | 无 | 否 | 清除当前会话，并停止数据端 |
| POST | `/api/exit` | 无 | 是 | 退出整个客户端 |
| POST | `/api/open-web/off` | 无 | 否 | 关闭启动后自动开页，适合无界面机器 |
| POST | `/api/autostart/on` | 无 | 是 | 设置当前用户自动启动；桌面环境使用 |

登录响应常见字段：

```json
{
  "ok": false,
  "needRecharge": true,
  "message": "请先充值"
}
```

当 `needRecharge=true` 时，账号凭据通常已经被接受，客户端可以继续调用充值接口；不要把它当作密码错误。

充值和启动响应重点看 `ok`：

```json
{"ok":true,"message":"充值成功"}
```

```json
{"ok":true,"port":8080}
```

## 5. 无依赖自动化脚本

示例合集提供 [`ai_control.py`](../examples/ai_control.py)，只使用 Python 标准库，不需要安装第三方包。它不会把密码或卡密拼到命令行参数中。

脚本默认管理地址是 `http://127.0.0.1:9527`，也可以设置 `DI_ADMIN_BASE`。

### 5.1 Linux / macOS

建议由密钥管理器注入环境变量；下面只展示变量名，不要把真实密码提交到脚本、工单或日志：

```bash
export DI_PHONE='你的手机号'
export DI_PASSWORD='你的密码'

python3 ai_control.py status
python3 ai_control.py login
python3 ai_control.py web-off
```

如果输出中的 `needRecharge` 为 `true`，注入卡密并继续：

```bash
export DI_CARD_KEY='你的卡密'
python3 ai_control.py recharge
python3 ai_control.py start --port 8080
python3 ai_control.py smoke
```

用完后清理当前 shell 的敏感变量：

```bash
unset DI_PHONE DI_PASSWORD DI_CARD_KEY
```

### 5.2 Windows PowerShell

```powershell
$env:DI_PHONE = '你的手机号'
$env:DI_PASSWORD = '你的密码'

python .\ai_control.py status
python .\ai_control.py login
python .\ai_control.py web-off
```

需要充值时：

```powershell
$env:DI_CARD_KEY = '你的卡密'
python .\ai_control.py recharge
python .\ai_control.py start --port 8080
python .\ai_control.py smoke
```

完成后清理变量：

```powershell
Remove-Item Env:DI_PHONE,Env:DI_PASSWORD,Env:DI_CARD_KEY -ErrorAction SilentlyContinue
```

AI 使用密钥仓库时，不要把真实值写进 PowerShell 历史、任务描述或异常信息；脚本输出的状态 JSON 也应按客户环境的日志策略保存。

## 6. 直接使用 curl / PowerShell

脚本不可用时，可以直接调用管理 API。真实凭据应由密钥管理器在运行时注入；不要把真实值写进命令文件。

Linux / macOS：

```bash
curl -fsS --max-time 5 http://127.0.0.1:9527/api/status

curl --silent --show-error --max-time 10 -X POST \
  http://127.0.0.1:9527/api/login \
  --data-urlencode "phone=${DI_PHONE}" \
  --data-urlencode "password=${DI_PASSWORD}"

curl --silent --show-error --max-time 10 -X POST \
  http://127.0.0.1:9527/api/recharge \
  --data-urlencode "cardKey=${DI_CARD_KEY}"

curl --silent --show-error --max-time 10 -X POST \
  http://127.0.0.1:9527/api/server/start \
  --data-urlencode "port=8080"
```

Windows PowerShell：

```powershell
Invoke-RestMethod -TimeoutSec 5 "http://127.0.0.1:9527/api/status"

$loginBody = @{ phone = $env:DI_PHONE; password = $env:DI_PASSWORD }
Invoke-RestMethod -Method Post -TimeoutSec 10 `
  -Uri "http://127.0.0.1:9527/api/login" -Body $loginBody

$rechargeBody = @{ cardKey = $env:DI_CARD_KEY }
Invoke-RestMethod -Method Post -TimeoutSec 10 `
  -Uri "http://127.0.0.1:9527/api/recharge" -Body $rechargeBody

$startBody = @{ port = '8080' }
Invoke-RestMethod -Method Post -TimeoutSec 10 `
  -Uri "http://127.0.0.1:9527/api/server/start" -Body $startBody
```

PowerShell 遇到 401/403 时可能直接抛出异常；自动化程序仍应读取 HTTP 错误响应正文，以判断是密码错误、需要充值还是权限已过期。

## 7. 服务器上启动客户端

### 7.1 Linux：先前台验证，再交给 systemd

把可执行文件放在固定目录，例如 `/opt/data-interface`，并确保运行用户对该目录有读写权限。目录旁可以放置：

```text
/opt/data-interface/data_interface
/opt/data-interface/web/api/catalog   # 仅使用本地目录或本地管理页时需要；无界面 API 不需要
/opt/data-interface/config.ini
/opt/data-interface/data_interface.log
```

无界面环境建议在 `config.ini` 中写入：

```ini
[General]
OpenWebOnLaunch=0
```

如果 `config.ini` 已经存在，请只编辑或追加 `[General]` 下的这一项，不要用整段示例覆盖原文件；原配置可能包含账号状态或设备信息。

先手动验证：

```bash
cd /opt/data-interface
chmod +x ./data_interface
./data_interface
```

另开终端确认：

```bash
curl -fsS --max-time 5 http://127.0.0.1:9527/api/status
```

确认管理端正常后，再创建 systemd 服务。下面的服务名和路径可以按实际部署修改：

```ini
[Unit]
Description=Data Interface local service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=data-interface
WorkingDirectory=/opt/data-interface
ExecStart=/opt/data-interface/data_interface
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

保存为 `/etc/systemd/system/data-interface.service` 后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now data-interface.service
sudo systemctl status data-interface.service
```

查看日志：

```bash
sudo journalctl -u data-interface.service -n 100 --no-pager
```

### 7.2 Windows Server

Windows 包不需要安装器。把 `data_interface.exe` 解压到固定目录，先在 PowerShell 中启动：

```powershell
$workDir = 'C:\DataInterface'
Start-Process -FilePath "$workDir\data_interface.exe" -WorkingDirectory $workDir
Start-Sleep -Seconds 2
Invoke-RestMethod -TimeoutSec 5 "http://127.0.0.1:9527/api/status"
```

服务器没有浏览器时，在程序目录的 `config.ini` 设置 `OpenWebOnLaunch=0`。长期运行请使用现有的任务调度器或进程管理器，并把工作目录固定为 EXE 所在目录。不要用“自启”按钮代替服务器进程管理：Windows 的自启设置面向当前用户登录会话。

### 7.3 macOS 无界面主机

当前 macOS 包是 Apple Silicon ARM64 DMG。首次安装和系统安全放行通常需要一次带桌面的登录会话；完成放行后，可以直接运行 App 包内的可执行文件：

```bash
mkdir -p "$HOME/Library/Application Support/DataInterface"
# 只有配置文件不存在时才创建；已有文件请手动只修改 OpenWebOnLaunch=0。
if [ ! -f "$HOME/Library/Application Support/DataInterface/config.ini" ]; then
  printf '[General]\nOpenWebOnLaunch=0\n' > "$HOME/Library/Application Support/DataInterface/config.ini"
fi

"/Applications/DataInterface.app/Contents/MacOS/data_interface" \
  > "$HOME/Library/Application Support/DataInterface/data_interface.log" 2>&1 &
```

然后用 `curl http://127.0.0.1:9527/api/status` 检查。macOS 使用单实例保护；旧进程仍在时，第二次启动会退出，应先停止旧进程。

## 8. 远程 AI 如何安全访问服务器

`127.0.0.1` 指的是“运行客户端的那台机器”。如果 AI 在服务器上，就直接访问服务器本机地址；如果人工或 AI 控制程序在另一台电脑上，推荐用 SSH 隧道：

```bash
ssh -N \
  -L 9527:127.0.0.1:9527 \
  -L 8080:127.0.0.1:8080 \
  user@server
```

隧道建立后，控制端访问自己的 `http://127.0.0.1:9527`，实际会转到服务器。若服务器启动时使用了其他 `proxyPort`，把隧道右侧端口和调用地址同步修改。

客户端内部监听地址可能覆盖到本机网卡，因此服务器部署必须由防火墙或安全组限制 9527、8080 的来源。不要把这两个端口直接暴露到公网，也不要把密码、卡密或 Token 放进 URL、公开日志或聊天记录。

## 9. 无界面自测

### 9.1 管理端

```bash
curl -fsS --max-time 5 http://127.0.0.1:9527/api/status
```

必须能得到 JSON。AI 应记录这些布尔状态：

```text
exeConnected=true
isLoggedIn=true
isVerified=true
running=true
```

### 9.2 数据端

先从状态 JSON 读取 `proxyPort`，再使用 9.3 的 D1 HTTP 请求测试数据端。
数据端没有独立的实时通道探活路径；D1 请求返回 JSON 即表示代理端口已响应。

### 9.3 D1 业务请求

D1 权限有效时：

```bash
curl -fsS --max-time 15 -X POST http://127.0.0.1:8080/d1/article \
  -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' \
  --data 'a=GetListByID&c=PCNewsFlash&LastID=0&st=1&Type=0'
```

HTTP 返回 JSON 即表示本地 HTTP 业务链路可以工作；业务是否成功还要按接口文档检查返回字段。`a` 和 `c` 是 D1 的固定协议字段，保持原值。

## 10. AI 故障分流

| 现象/状态 | AI 应判定为 | 下一步 |
|---|---|---|
| 9527 无响应 | 客户端进程或管理端未就绪 | 检查进程、工作目录、日志和端口；等待后再轮询 |
| `/api/status` 有 JSON，`isLoggedIn=false` | 未登录 | 调用 `/api/login`，不要依赖页面 |
| `isLoggedIn=true`，`needRecharge=true` 或 `isVerified=false` | 账号无有效权限 | 调用 `/api/recharge`；没有卡密时转人工支持 |
| `isVerified=true`，`running=false` | 数据端尚未启动 | 调用 `/api/server/start` |
| `running=true`，业务请求连接失败 | 端口或调用地址错误 | 使用 `/api/status` 的 `proxyPort`，不要固定写 8080 |
| 数据接口 403 | 目标产品未授权或会话失效 | 检查 `products`、有效期和登录状态，不要反复安装 |
| `api/status` 有 JSON 但浏览器打不开 | 仅缺少网页环境或网页地址错误 | 无界面场景继续使用 API；桌面场景访问 9527 |
| 启动后立即退出 | 架构、权限、端口、配置或旧实例问题 | 先看进程日志和崩溃目录，再检查 `uname -m`/工作目录 |

## 11. 提交给 AI/技术支持的结构化信息

推荐只提交以下脱敏字段：

```text
os: Windows / macOS / Linux
arch: AMD64 / arm64 / x86_64
package: data_interface_*.zip / .dmg / .tar.gz
step: start-process / status / login / recharge / start / smoke
admin_status: <粘贴 /api/status，确认手机号已脱敏>
data_probe: <D1 业务请求的 HTTP 状态和前 200 个字符>
error: <完整错误文字>
```

不要提交：密码、卡密、Token、完整配置文件、包含凭据的环境变量、未脱敏的长日志。
