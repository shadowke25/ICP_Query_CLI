# ICP_Query_CLI

CLI-focused derivative of [HG-ha/ICP_Query](https://github.com/HG-ha/ICP_Query), built for fast ICP filing lookups in authorized reconnaissance workflows.

The original web/API implementation is preserved for attribution and reference. The standalone CLI lives in [`icp-query-cli/`](icp-query-cli/README.md); the upstream README is kept as [`README_UPSTREAM.md`](README_UPSTREAM.md).

## Highlights

- Single command `icp-query`, no Web UI or service dependencies
- Query by domain, URL, IP (PTR), company name, or filing number
- Supports websites, apps, mini programs, quick apps, and violation blacklists
- Outputs `text`, `brief`, `json`, `jsonl`, and `raw`
- Stable exit codes for scripts and agent toolchains: `0` found, `2` no record, `1` failure, `64` usage error
- Token cache, SOCKS5/HTTP proxy, retry, pagination, and request timeouts
- One-step Kali Linux installer with global command registration

## Quick start

```bash
cd icp-query-cli
chmod +x install.sh uninstall.sh
./install.sh

icp-query baidu.com
icp-query -q -f json baidu.com
icp-query -q -f brief qq.com
```

Extract core fields:

```bash
icp-query -q -f json baidu.com \
  | jq -r '.results[0].records[0] | [.unit_name, .main_licence, .service_licence, .nature_name] | @tsv'
```

Example result:

```json
{
  "provider": "miit",
  "type": "web",
  "ok": true,
  "found": true,
  "results": [
    {
      "target": "baidu.com",
      "records": [
        {
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

## Fork policy

This repository is an intentionally divergent, CLI-focused derivative:

- It is **not** intended to be merged back into `HG-ha/ICP_Query`.
- No upstream pull requests will be opened from this repository.
- Upstream changes are not automatically merged; upstream code is kept as a reference base.
- CLI work is isolated under `icp-query-cli/` so the upstream implementation remains identifiable.

## Scope

Use this tool only for authorized security testing and asset attribution. It queries public MIIT ICP filing data and does not bypass access controls. See [`icp-query-cli/README.md`](icp-query-cli/README.md) for installation, configuration, output schema, and troubleshooting.

## Attribution

Based on [HG-ha/ICP_Query](https://github.com/HG-ha/ICP_Query) v0.7.6. The upstream project did not include a LICENSE file; review the upstream repository terms before redistribution.
