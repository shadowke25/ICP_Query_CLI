# ICP_Query_CLI

面向授权信息收集场景的工信部 ICP 备案查询命令行工具，基于
[HG-ha/ICP_Query](https://github.com/HG-ha/ICP_Query) v0.7.6 二次开发。

当前分支只保留独立 CLI，已移除上游的 Web UI、Python/Rust 服务、Docker 部署、静态资源、ONNX 模型和非必要配置；上游提交历史仍保留在 Git 历史中用于溯源。

完整安装、参数、输出结构、配置与问题排查请见
[`icp-query-cli/README.md`](icp-query-cli/README.md)。

## 功能特性

- 单命令 `icp-query`，无 Web 服务、无数据库、无 MCP 依赖
- 支持域名、URL、IP（PTR 反查）、单位名称、备案号查询
- 支持网站、APP、小程序、快应用，以及违法违规黑名单
- 输出 `text`、`brief`、`json`、`jsonl`、`raw` 五种格式
- 稳定退出码：`0` 命中、`2` 无记录、`1` 失败、`64` 参数错误
- 内置 token 缓存、HTTP/SOCKS5 代理、重试、分页与超时控制
- Kali Linux 一键安装，自动注册全局命令
- 保留上游鉴权、创宇盾识别、滑块验证码识别和 APP 详情并发逻辑

## 快速开始

```bash
cd icp-query-cli
chmod +x install.sh uninstall.sh
./install.sh

icp-query baidu.com
icp-query -q -f json baidu.com
icp-query -q -f brief qq.com
```

### 常用命令

```bash
# 域名（最常用）
icp-query -q -f json example.com

# 单位名称，每页最多 26 条，可配合 -p 翻页
icp-query -q -f json -t web -s 26 -p 1 "公司全称"

# 备案号反查
icp-query -q -f json "京ICP证030173号"

# APP / 小程序 / 快应用
icp-query -q -f json -t app "应用名"
icp-query -q -f json -t mapp "小程序名"
icp-query -q -f json -t kapp "快应用名"

# 违法违规黑名单
icp-query -q -f json -t bweb example.com

# 批量目标，每行一个，2-4 并发
icp-query -q -f jsonl -j 4 - < targets.txt
```

### 提取核心字段

```bash
icp-query -q -f json baidu.com \
  | jq -r '.results[0].records[0] | [.unit_name, .main_licence, .service_licence, .nature_name] | @tsv'
```

- `unit_name`：主办单位 / 备案主体
- `main_licence`：主体备案号
- `service_licence`：网站或服务备案号
- `nature_name`：主体类型（企业 / 事业单位 / 个人等）
- `domain`：备案域名；`update_time`：审核时间

## 输出示例

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
      "count": 1,
      "total": 1,
      "pages": 1,
      "records": [
        {
          "domain": "baidu.com",
          "unit_name": "北京百度网讯科技有限公司",
          "main_licence": "京ICP证030173号",
          "service_licence": "京ICP证030173号-1",
          "nature_name": "企业"
        }
      ]
    }
  ]
}
```

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 查询成功且至少命中一条记录 |
| `2` | 查询成功但无备案记录 |
| `1` | 查询失败（网络、验证码、创宇盾拦截、IP 无 PTR 等） |
| `64` | 参数错误 |
| `130` | Ctrl+C 中断 |

## 仓库结构

```text
.
├── README.md
├── .gitignore
└── icp-query-cli/
    ├── README.md
    ├── pyproject.toml
    ├── install.sh
    ├── uninstall.sh
    └── src/icp_query_cli/
        ├── cli.py        # 参数解析、执行编排、退出码
        ├── core.py       # 鉴权、滑块、查询、详情并发
        ├── captcha.py    # 滑块缺口识别
        ├── targets.py    # URL/域名/IP/关键词归一化
        ├── output.py     # 结果归一化与多格式输出
        └── config.py     # 配置加载
```

## 分支策略

本仓库是面向 CLI 场景的独立分支：

- 不向 `HG-ha/ICP_Query` 提交 PR，也不接受上游自动合并
- 上游代码已从当前分支移除，仅保留来源说明与 Git 历史
- CLI 的后续开发只维护 `icp-query-cli/`，不再跟随上游 Web/Rust 功能
- 该仓库在 GitHub 上是独立仓库，不处于 fork 网络，不存在自动合并通道

## 来源与使用范围

- 基于 [HG-ha/ICP_Query](https://github.com/HG-ha/ICP_Query) v0.7.6
- 上游项目未附带 LICENSE 文件，分发前请自行确认上游仓库说明
- 仅用于授权范围内的安全测试与信息收集，请勿用于未授权目标
