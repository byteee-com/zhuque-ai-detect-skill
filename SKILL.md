---
name: zhuque-ai-detect-skill
description: 用腾讯朱雀检测 AI 生成特征。文本默认走 EdgeOne Makers API，支持分段评分、批量查稿和两版对照。企业 Pro 支持文本和图片。需要网页版或视频检测时提供朱雀官网链接，供用户手动操作。
---

# 朱雀 AI 检测

先确定用户要检测的内容和通道。只提交用户指定的材料。检测需要将这些材料发给腾讯。

| 请求 | 通道 |
| --- | --- |
| 文本、分段评分、批量文本、两版稿件对照 | 默认走普通 [Makers API](references/api.md)。未配置 Key 时请用户在已安装的 Skill 目录打开终端并运行 `python3 scripts/zhuque.py setup`，Windows PowerShell 使用 `py -3 .\scripts\zhuque.py setup`。配置无效时用 `doctor` 查看原因 |
| 明确指定官网或浏览器 | 提供[文本检测](https://matrix.tencent.com/ai-detect/ai_gen_txt)或[图片与视频检测](https://matrix.tencent.com/ai-detect/ai_gen)链接，由用户手动检测 |
| 图片或视频，未指定企业 Pro | 提供[官网手动检测链接](https://matrix.tencent.com/ai-detect/ai_gen) |
| 明确指定企业 Pro | [Pro API](references/api.md)，支持同步检测文本和图片，可逐项批量。这个通道按次计费 |

网页版只提供链接。不调用浏览器工具，不代填、上传、点击或提交。API 提交失败时说明状态，由用户决定是否重试或手动检测。

## 处理输入与结果

- 从本 Skill 目录定位 `scripts/zhuque.py`。Agent 在其他目录运行时，用脚本的绝对路径，并保留用户文件路径的原始指向。
- API 文本从标准输入或用户指定的 TXT、Markdown、DOCX 读取。保留原文和顺序。需要分段得分时加 `--paragraphs`，对照两版时用 `batch --compare`。
- 批量先用 `batch --dry-run` 检查明确列出的文件和数量，再逐项提交。报告中区分成功、失败与未提交。
- 标明来源。API 分开报告人工、AI 和疑似 AI 的内容占比，以及朱雀返回的分段标签和置信度。用户提供网页结果时，可根据其中可见的指标整理或对比。整体分数、段落置信度与内容占比是不同的指标。
- 默认不显示原文或段落摘录。报告可导出为 Markdown 或 JSON。将检测结论用作复核线索，结合其他证据判断来源。
