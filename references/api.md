# EdgeOne API 配置与用法

普通 Makers 的 Key 在 EdgeOne 控制台的 Makers → Models → API Key 创建。企业 Pro 需要已开通的企业网关、控制台分配的 HTTPS 网关域名和独立 API Key。企业调用会计费。见 [普通 Makers 文档](https://cloud.tencent.com/document/product/1552/137539)和[企业 Pro 文档](https://cloud.tencent.com/document/product/1552/135974)。

脚本使用 Python 3.10+，运行时仅依赖标准库。配置普通 Makers 时，在项目目录打开自己的终端并运行 `setup`，按提示粘贴 Key。输入不回显，配置保存在当前用户的目录。换 Key 时再次运行 `setup`。

| 系统 | 配置普通 Makers Key | 本地自检 |
| --- | --- | --- |
| Windows PowerShell | `py -3 .\scripts\zhuque.py setup` | `py -3 .\scripts\zhuque.py doctor` |
| macOS / Linux | `python3 scripts/zhuque.py setup` | `python3 scripts/zhuque.py doctor` |

## 环境变量与企业 Pro 配置

需要用环境变量注入凭证或手动配置企业 Pro 时，使用下表中的字段。把真实值留在本机配置或运行环境中。

| 环境变量或 JSON 键 | 用途 |
| --- | --- |
| `MAKERS_MODELS_KEY` | 普通 Makers Key |
| `ZHUQUE_PRO_GATEWAY` | 控制台分配的企业 HTTPS 网关 origin，如 `https://gateway.example.com` |
| `ZHUQUE_PRO_API_KEY` | 与该网关配套的企业 Key |

也可以编辑 `~/.config/zhuque-detect/credentials.json`，Windows 对应 `$HOME\.config\zhuque-detect\credentials.json`。只填写需要的通道。macOS/Linux 下文件须归当前用户且仅本人可读写，例如权限 `0600`。需要手动创建文件时，macOS/Linux 可以用以下命令准备。

```sh
mkdir -p ~/.config/zhuque-detect
(umask 077 && touch ~/.config/zhuque-detect/credentials.json)
chmod 600 ~/.config/zhuque-detect/credentials.json
```

```json
{
  "MAKERS_MODELS_KEY": "替换为普通 Makers Key",
  "ZHUQUE_PRO_GATEWAY": "https://gateway.example.com",
  "ZHUQUE_PRO_API_KEY": "替换为企业 Pro Key"
}
```

环境变量优先。只要设置了任一企业环境变量，两个企业字段就必须一起在环境中提供，以免把 Key 发给另一套配置的网关。网关地址只填 origin，不能带路径、查询参数或用户名。配置错误时 `doctor` 会给出原因，不回显密钥或网关。

## 命令

从 Skill 目录运行，或将脚本路径换成实际位置。

```sh
python3 scripts/zhuque.py doctor
python3 scripts/zhuque.py text --stdin < 稿件.txt
python3 scripts/zhuque.py text --file 稿件.docx --paragraphs --format markdown
python3 scripts/zhuque.py batch --dry-run 初稿.md 修改稿.docx
python3 scripts/zhuque.py batch --compare --paragraphs --format markdown 初稿.md 修改稿.docx
python3 scripts/zhuque.py text --provider pro --file 稿件.md
python3 scripts/zhuque.py image --provider pro --file 图片.png
python3 scripts/zhuque.py image --provider pro --url https://example.com/image.jpg
python3 scripts/zhuque.py batch --provider pro --dry-run 稿件.docx 图片.png
```

- `text --stdin` 读取 UTF-8 粘贴文本或管道输入。TXT/Markdown 按原文读取。DOCX 提取正文和表格文字，保留文档顺序，不含页眉、批注或嵌入媒体。API 默认合并段落，`--paragraphs` 请求独立分段评分。分段位置保留服务给出的原始偏移，报告按服务返回的段落编号定位。
- Pro 图片支持 JPG、PNG、WebP，官方要求宽高均超过 300 像素、大小限制 10 MB。脚本提交本地文件时编码为 Base64，提交 URL 时由服务端读取该地址。批量可列出文本文件，选择 Pro 时也可混入本地图片。
- `batch --dry-run` 不读取凭证或联网。实际执行也会先检查全部输入，再按参数顺序提交。服务拒绝单项输入时可继续，限流、额度、鉴权或状态不明时停止。未返回扣减值的请求不计入已知用量，汇总会提示缺失。
- 默认输出 JSON，可用 `--format markdown` 输出报告。按需将标准输出保存到新文件。退出码 `0` 表示全部成功或检查通过，`1` 表示有失败或未提交项，`2` 表示命令或配置不可用。即使部分失败，也应保留报告。
- `batch --compare` 恰好接收两份文本，同一通道与设置下计算第二份减第一份的占比差，单位是百分点。两份都成功才出对照数据。
- `makers_models_usage.total_tokens` 是本次实际扣减的 Makers token，`usage.total_tokens` 是朱雀模型统计。不要用后者估算账户扣减。Pro 的账单以腾讯云为准。
