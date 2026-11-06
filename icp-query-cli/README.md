# ICP_Query CLI

面向渗透测试信息收集的工信部 ICP 备案查询命令行工具，基于
[HG-ha/ICP_Query](https://github.com/HG-ha/ICP_Query) v0.7.6 二次开发：

- 保留原有核心链路：工信部实时接口、创宇盾拦截识别、滑块验证码识别、分页查询、APP/小程序详情并发获取
- 移除 Web UI、代理池、IPv6 轮询等 CLI 不需要的模块，改为单进程命令
- 新增命令行参数、目标归一化（域名/URL/IP/单位名称/备案号）、结构化输出与稳定退出码
- 面向 Kali Linux 提供一键安装脚本，安装后可直接全局调用 `icp-query`

> 仅用于授权的安全测试与信息收集，请遵守《网络安全法》及目标授权范围。上游项目声明仅用于学习交流逆向与验证码识别技术。

## 功能与查询对象

| 查询对象 | 示例 | 说明 |
|----------|------|------|
| 域名 | `icp-query baidu.com` | 最常用，返回主体、备案号、主体类型 |
| URL | `icp-query https://www.qq.com/index.html` | 自动提取 host 后查询 |
| IP | `icp-query 8.8.8.8` | 先做 PTR 反查域名；无 PTR 时明确报错（工信部接口不支持按 IP 查备案） |
| 单位名称 | `icp-query 深圳市腾讯计算机系统有限公司` | 可一次拿到该主体名下多条备案 |
| 备案号 | `icp-query 京ICP证030173号` | 反查主体与域名 |
| 管道批量 | `cat domains.txt \| icp-query -f jsonl -` | 每行一个目标，自动去重 |

支持的查询类型：`web`（默认）、`app`、`mapp`、`kapp`、`bweb`、`bapp`、`bmapp`、`bkapp`。

## Kali Linux 安装

### 环境要求

- Kali Linux 2023.4+（amd64 / arm64 均可）
- Python >= 3.10，已安装 `python3-venv`
- 可访问 `hlwicpfwc.miit.gov.cn`（需要出网）
- 依赖由安装脚本自动处理：`aiohttp`、`aiohttp-socks`、`numpy`、`Pillow`、`PyYAML`；不依赖 onnxruntime / ujson

### 一键安装（推荐）

```bash
sudo apt update && sudo apt install -y python3 python3-venv
cd icp-query-cli
chmod +x install.sh uninstall.sh
./install.sh
```

脚本会：

1. 在 `~/.local/share/icp-query/venv` 创建独立虚拟环境（规避 Kali 的 PEP 668 限制）
2. 安装依赖并注册 `icp-query` 命令
3. 优先软链到 `~/.local/bin/icp-query`；若该目录不在 `PATH`，且 `/usr/local/bin` 可写或 sudo 免密，则软链到 `/usr/local/bin`
4. 输出 `icp-query --version` 验证结果

若 sudo 需要密码且 `~/.local/bin` 不在 `PATH`，脚本会提示配置 `PATH`；也可手动全局注册：

```bash
sudo ln -sfn "$HOME/.local/share/icp-query/venv/bin/icp-query" /usr/local/bin/icp-query
```

验证：

```bash
icp-query --version
icp-query --list-types
icp-query baidu.com
```

### 手动安装

```bash
python3 -m venv ~/.local/share/icp-query/venv
~/.local/share/icp-query/venv/bin/pip install --upgrade pip
~/.local/share/icp-query/venv/bin/pip install /path/to/icp-query-cli
chmod +x ~/.local/share/icp-query/venv/bin/icp-query
mkdir -p ~/.local/bin
ln -sfn ~/.local/share/icp-query/venv/bin/icp-query ~/.local/bin/icp-query
```

确保 `~/.local/bin` 在 `PATH` 中；未生效时执行 `export PATH="$HOME/.local/bin:$PATH"` 或重开终端。

### 卸载

```bash
./uninstall.sh
```

若曾通过 `sudo` 注册到 `/usr/local/bin`，卸载时会提示手动删除；也可直接执行：

```bash
sudo rm -f /usr/local/bin/icp-query
```

## 使用方式

```bash
# 基础查询
icp-query baidu.com

# JSON 输出（供程序/Agent 解析）
icp-query -f json baidu.com

# 单位名称查询，每页 26 条
icp-query -t web -s 26 深圳市腾讯计算机系统有限公司

# 查询 APP 备案
icp-query -t app -f json 微信

# 违法违规黑名单查询
icp-query -t bweb baidu.com

# 批量并发查询（默认 1 个并发，稳妥防拦截）
icp-query -j 4 -f jsonl baidu.com qq.com 8.8.8.8

# 从管道读取
cat domains.txt | icp-query -f jsonl -

# 走代理（HTTP 或 SOCKS5）
icp-query --proxy socks5://127.0.0.1:1080 baidu.com
```

### 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `TARGET...` | 必填 | 域名 / URL / IP / 单位名称 / 备案号；`-` 表示从 stdin 读取 |
| `-t, --type` | `web` | `web`/`app`/`mapp`/`kapp`/`bweb`/`bapp`/`bmapp`/`bkapp` |
| `-p, --page` | `1` | 页码，从 1 开始 |
| `-s, --size` | `10` | 每页条数，范围 1-26（接口限制） |
| `-f, --format` | `text` | `text`/`brief`/`json`/`jsonl`/`raw` |
| `-j, --jobs` | `1` | 批量并发数 1-8；调高可能触发风控 |
| `--timeout` | `15` | 单次请求超时 3-120 秒 |
| `--retry` | `3` | 单目标最大尝试次数 1-10，每次重新过滑块 |
| `--proxy` | 无 | `http://host:port` 或 `socks5://host:port` |
| `--no-captcha` | 关闭 | 使用内置 fallback sign，可能过期，仅作应急 |
| `--no-cache` | 关闭 | 不缓存 token |
| `--color` | `auto` | `auto`/`always`/`never` |
| `-q, --quiet` | 关闭 | 静默，仅输出结果 |
| `-v, -vv` | 关闭 | 日志级别（stderr） |
| `--list-types` | - | 列出类型并退出 |
| `--version` | - | 显示版本 |

### 输出格式

**text（默认）**

```
▌ baidu.com  [web]
  共 1 条 / 1 页，本页 1 条

  [1] baidu.com
      主体名称: 北京百度网讯科技有限公司
      备案主体号: 京ICP证030173号
      备案服务号: 京ICP证030173号-1
      主体类型: 企业
      审核时间: 2019-05-16 16:06:21
```

**brief（Tab 分隔，便于 grep/awk）**

```
域名  主体名称  备案主体号  备案服务号  主体类型
baidu.com  北京百度网讯科技有限公司  京ICP证030173号  京ICP证030173号-1  企业
```

**json（稳定结构，推荐给 Agent/harness）**

```json
{
  "provider": "miit",
  "type": "web",
  "page": 1,
  "size": 10,
  "ok": true,
  "found": true,
  "results": [
    {
      "target": "baidu.com",
      "query": "baidu.com",
      "kind": "domain",
      "ok": true,
      "code": "OK",
      "message": null,
      "count": 1,
      "total": 1,
      "pages": 1,
      "records": [
        {
          "domain": "baidu.com",
          "unit_name": "北京百度网讯科技有限公司",
          "main_licence": "京ICP证030173号",
          "service_licence": "京ICP证030173号-1",
          "nature_name": "企业",
          "update_time": "2019-05-16 16:06:21"
        }
      ]
    }
  ]
}
```

- `ok`：查询链路是否成功（无网络/验证码/接口错误）
- `found`：是否命中记录
- `records`：已归一化字段；核心字段为 `unit_name`、`main_licence`、`service_licence`、`nature_name`
- `raw`：上游原始响应，仅在 `-f raw` 时输出

`jsonl` 为每个目标一行 JSON；`raw` 为工信部原始结构，便于排查字段变化。

### 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 查询成功且至少命中一条记录 |
| `2` | 查询成功但无记录 |
| `1` | 查询失败（网络、验证码、接口异常、被创宇盾拦截、IP 无 PTR 等） |
| `64` | 参数错误 |
| `130` | Ctrl+C 中断 |

## 脚本与批量调用

CLI 无交互，结果走 stdout、日志走 stderr，可直接在 shell 或 Agent 工具链中调用：

```bash
icp-query -q -f json --timeout 15 --retry 2 <target>
```

提取核心信息：

```bash
icp-query -q -f json baidu.com \
  | jq -r '.results[0].records[0] | [.unit_name, .main_licence, .service_licence, .nature_name] | @tsv'
```

批量目标建议使用 `-f jsonl`，逐行解析，避免一次性聚合：

```bash
icp-query -q -f jsonl -j 4 < targets.txt
```

## 配置

优先级：命令行参数 > 环境变量 > 用户配置 > 内置默认配置。

用户配置路径：`~/.config/icp-query/config.yml`（可用 `ICP_QUERY_CONFIG` 指定其他路径）。

```yaml
network:
  timeout: 15
  retries: 3
  proxy: null          # http://127.0.0.1:8080 / socks5://127.0.0.1:1080

captcha:
  enable: true
  detail_concurrency: 3

cache:
  enable: true
  dir: null            # 默认 ~/.cache/icp-query

output:
  color: auto
```

环境变量：`ICP_QUERY_CONFIG`、`ICP_QUERY_PROXY`、`ICP_QUERY_TIMEOUT`、`ICP_QUERY_CAPTCHA`
（`0/false/off` 关闭）、`ICP_QUERY_CACHE`、`ICP_QUERY_CACHE_DIR`、`NO_COLOR`。

## 性能与稳定性

- 单域名查询实测约 1-2 秒（Kali WSL2 / Python 3.14 实测 1.22 秒，含鉴权 + 滑块识别 + 查询）
- 滑块识别为纯 numpy 实现，约 100-150ms，无需 onnx runtime
- 请求体采用紧凑 JSON（与上游 ujson 行为一致），因此无需额外安装 ujson，也避免 Linux 环境下签名校验失败
- token 会缓存到 `~/.cache/icp-query/token.json`（`0600`），命中缓存可省一次鉴权往返
- 每次失败重试都会重新获取验证码；遇到“创宇盾拦截”立即返回，不继续硬刷
- 批量默认串行；`-j` 调高可提速，但更容易触发频控，建议 2-4

## 常见问题

**`icp-query: command not found`**

`~/.local/bin` 不在 `PATH`：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`error: externally-managed-environment`**

不要直接 `pip install` 到系统 Python；使用本项目 `install.sh` 的 venv 方式。

**返回“未查询到备案信息”**

- 确认输入的是主域名（如 `qq.com`，`www.qq.com` 可能无独立备案记录）
- 确认该域名已完成 ICP 备案
- 境外域名/未备案域名不会返回记录

**返回“该 IP 无 PTR 记录”**

工信部接口按域名/主体查询，不支持直接按 IP 反查。请先通过其他手段拿到域名，再用域名查询。

**验证码识别失败 / 被创宇盾拦截**

- 默认会自动重试 3 次；仍失败可适当降低并发、换出口 IP/代理
- 不要关闭验证码（`--no-captcha`）作为长期方案，内置 sign 会过期

**接口字段变化**

先用 `-f raw` 查看上游原始响应；本项目只依赖 `params.list` 与常见字段，字段缺失时会优雅降级。

## 项目结构

```text
icp-query-cli/
├── pyproject.toml
├── install.sh / uninstall.sh
├── src/icp_query_cli/
│   ├── cli.py        # 参数解析、执行编排、退出码
│   ├── core.py       # 鉴权、滑块、查询、详情并发（重构自 ymicp.py）
│   ├── captcha.py    # 缺口识别（移植自上游）
│   ├── targets.py    # URL/域名/IP/关键词归一化与 PTR
│   ├── output.py     # 归一化、text/brief/json/jsonl/raw
│   ├── config.py     # 配置加载
│   └── config.default.yml
```

## 验证记录

2026-11-06 在 Windows 主机、Kali Linux（WSL2）及独立 Kali 主机（Python 3.14.7）真实网络环境验证：

| 场景 | 命令 | 结果 |
|------|------|------|
| Kali 全新安装 | `./uninstall.sh && ./install.sh` | 全局命令 `/usr/local/bin/icp-query`，`icp-query --version` 正常 |
| 独立 Kali 主机（SSH） | `icp-query -q -f json baidu.com` | 全局命令可用，返回百度备案信息，耗时 1.409s |
| 域名（Kali） | `icp-query baidu.com` | 北京百度网讯科技有限公司 / 京ICP证030173号 / 企业，退出码 0，耗时 1.22s |
| URL 归一化 | `icp-query -f json https://www.qq.com/index.html` | 正确提取 `www.qq.com`，无记录，退出码 2 |
| 单位名称 | `icp-query -f brief qq.com` | 深圳市腾讯计算机系统有限公司 / 粤B2-20090059 |
| APP 详情（Kali） | `icp-query -t app -s 5 -f json 微信` | 返回服务备案号 `粤B2-20090059-1621A` |
| 黑名单（Kali） | `icp-query -t bweb baidu.com` | 威胁等级 2（暂无违法违规信息） |
| IP + PTR（Kali） | `icp-query -f json 8.8.8.8` | 反查为 `dns.google` 后查询，无记录，退出码 2 |
| IP 无 PTR | `icp-query 1.2.3.4` | 明确提示改用域名，退出码 1 |
| 批量/并发 | `icp-query -f json -j 2 baidu.com qq.com` | 两条结果，退出码 0 |
| 管道输入 | `cat domains.txt \| icp-query -f brief -` | 正确逐行查询 |
| 参数校验 | `icp-query -s 30 baidu.com` | 退出码 64 并提示 1-26 |

## 说明

- 本项目未包含上游 Web UI/数据库/鉴权等模块，仅保留查询核心
- 上游项目未附带 LICENSE 文件，二次开发与分发前请遵循上游仓库说明
- 工信部接口与验证码策略可能随时调整，如遇持续失败请先 `-f raw -vv` 排查
