<p align="center">
  <img src="assets/readme/zhuque-banner-zh.png" alt="朱雀 AI 生成内容检测，支持分段检测、批量送检和两版对照" width="100%">
</p>

# 朱雀 AI 检测 Skill

![运行环境为 Python 3.10+ 和 macOS、Linux 或 Windows，默认接口为 EdgeOne Makers API](assets/readme/environment-badges.svg)

把稿件交给 Agent，就能用腾讯朱雀检测 AI 生成特征、定位可疑分段，或比较两版稿件。**文本默认走 EdgeOne Makers API。**

**简体中文** · [English](README.en.md)　|　[功能列表](#features) · [安装 Skill](#install) · [配置 Key](#key) · [使用方法](#usage) · [命令行](#cli)

<a name="features"></a>

## 功能列表

| 功能 | 输入 | 返回结果 |
| --- | --- | --- |
| 单篇与分段检测 | 粘贴正文、TXT、Markdown、DOCX | 人工、AI、疑似 AI 的内容占比和分段标签 |
| 批量检测 | 指定多份稿件 | 每份稿件的结果，区分成功、失败和未提交 |
| 两版对照 | 初稿和修改稿 | 各类内容占比的百分点变化，以及两版的分段结果 |
| 报告导出 | 单篇、批量或对照结果 | Markdown 或 JSON，默认省略原文 |
| 企业 Pro | 文本、图片文件或公网图片 URL | 文本分段结果或图片的 AI 置信度。需显式选择，按次计费 |
| 朱雀官网 | 文本、图片或视频 | 用户手动打开[文本检测](https://matrix.tencent.com/ai-detect/ai_gen_txt)或[图片与视频检测](https://matrix.tencent.com/ai-detect/ai_gen) |

API 检测会把你指定的内容发送给腾讯。内容占比与分段置信度分开报告，结果供复核参考。

<a name="install"></a>

## 安装 Skill

推荐用 [Skills CLI](https://github.com/vercel-labs/skills) 一键安装。先准备 **Node.js 22.20+**（含 `npx`）和 Git。检测本身需要 **Python 3.10+**，以及能访问腾讯云的 Agent 运行环境。

在终端运行。下面以 Codex 为例，macOS、Linux 和 Windows PowerShell 使用同一条命令。

```sh
npx skills add byteee-com/zhuque-ai-detect-skill --global --agent codex --yes
```

用 Claude Code 或 Cursor 时，将 `--agent codex` 改为下表的参数。只想安装到当前项目时，去掉 `--global`。安装后新开一个 Agent 对话。

| Agent | `--agent` 参数或安装方式 | 在对话中调用 |
| --- | --- | --- |
| **Codex** | `codex` | 输入 `$` 选择 Skill。 [官方文档](https://developers.openai.com/codex/skills) |
| **Claude Code** | `claude-code` | 输入 `/zhuque-ai-detect-skill`。 [官方文档](https://code.claude.com/docs/en/skills) |
| **Cursor** | `cursor` | 在本地 Agent 对话中用 `/` 选择 Skill。 [官方文档](https://cursor.com/docs/skills) |
| **WorkBuddy** | 「技能 → 添加技能 → 上传技能」，导入 ZIP 包 | 在对话中点名 `zhuque-ai-detect-skill`。 [官方文档](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market) |

已在 macOS 验证 Skills CLI 能安装到 Codex、Claude Code 和 Cursor 的目录，并用 Codex 完成实际 API 检测。

<details>
<summary>手动安装或导入 WorkBuddy</summary>

在 [GitHub 仓库](https://github.com/byteee-com/zhuque-ai-detect-skill) 点 **Code → Download ZIP** 并解压，也可以用 Git 克隆。

把 `SKILL.md`、`agents/`、`scripts/` 和 `references/` 放在名为 `zhuque-ai-detect-skill` 的目录中。

- **Codex**：把该目录放到 `~/.agents/skills/`。
- **Claude Code**：把该目录放到 `~/.claude/skills/`。
- **Cursor**：把该目录放到 `~/.cursor/skills/`。
- **WorkBuddy**：把该目录压缩为 ZIP，再通过「上传技能」导入。
</details>

<a name="key"></a>

## 配置 Key

在 EdgeOne 控制台的 **Makers → Models → API Key** 创建普通 Makers Key。参见 [腾讯云朱雀接入文档](https://cloud.tencent.com/document/product/1552/137539)。

按上面的全局命令安装后，在终端进入 Skill 目录。项目级或手动安装时，进入对应的实际目录。

**macOS / Linux**

```sh
cd ~/.agents/skills/zhuque-ai-detect-skill
python3 scripts/zhuque.py setup
python3 scripts/zhuque.py doctor
```

**Windows PowerShell**

```powershell
Set-Location "$HOME\.agents\skills\zhuque-ai-detect-skill"
py -3 .\scripts\zhuque.py setup
py -3 .\scripts\zhuque.py doctor
```

运行 `setup` 时按提示粘贴 Key 并回车。输入不会回显，脚本会保存到当前用户的本机配置。换 Key 时再次运行 `setup`。

`doctor` 显示 `makers.status: ready` 表示配置可读取。第一次 API 检测会验证 Key 是否有效。环境变量和企业 Pro 的配置见 [API 配置说明](references/api.md)。

<a name="usage"></a>

## 使用方法

在 Agent 对话中附上稿件、粘贴正文，或提供 Agent 能读取的文件路径。按上表选中 Skill，也可以在提示词里点名。Agent 会调用脚本并在对话里返回报告。

<p align="center">
  <img src="assets/readme/agent-chat-zh.gif" alt="中文对话示意。用户提交一篇稿件，Agent 通过 Makers API 返回内容占比、分段置信度和 token 用量。" width="900">
</p>

<p align="center"><sub>对话界面为示意，报告中的数字来自实际 API 测试。</sub></p>

**检测单篇，查看分段**

```text
用 zhuque-ai-detect-skill 检测我提供的稿件。
列出人工、AI、疑似 AI 的内容占比，按分段编号给出标签和置信度，并报告实际扣减 token。
```

**比较两版稿件**

```text
用 zhuque-ai-detect-skill 对照初稿.md 和修改稿.docx。
用同样的分段设置检测两版，列出各类内容占比的百分点变化，并标出各自值得复核的分段。
```

**批量检测并保存报告**

```text
用 zhuque-ai-detect-skill 批量检测 A.md、B.docx 和 C.txt。
先预检这三个文件，再逐份检测。将成功、失败和未提交项写入 report.md，省略原文。
```

**仅做本地预检**

```text
用 zhuque-ai-detect-skill 预检初稿.md 和修改稿.docx。
只检查路径、格式和可读性，不调用 API。
```

<a name="cli"></a>

## 命令行

Python 命令也可以独立使用，适合本地检查、脚本集成和报告导出。在已安装的 Skill 目录或仓库根目录运行。Windows 用户将 `python3 scripts/zhuque.py` 换成 `py -3 .\scripts\zhuque.py`。

```sh
python3 scripts/zhuque.py text --file draft.docx --paragraphs --format markdown
python3 scripts/zhuque.py batch --dry-run first.md revised.docx
python3 scripts/zhuque.py batch --compare --paragraphs first.md revised.docx
```

命令行默认输出 JSON。更多参数和错误状态见 [API 配置与命令参考](references/api.md)。

## 关于守一科技

[守一科技官网](https://www.byteee.com)

[![守一科技｜让 AI 真正进入工作与业务。自研 AI 产品，企业 AI 落地（FDE）。](assets/readme/byteee-banner.png)](https://www.byteee.com)

## 开源许可

本项目采用 [MIT 许可证](LICENSE)。
