# Report lifecycle

内部状态仍保持可审计的状态机：

```text
uploaded → parsing → needs_review → ready_to_publish → published → withdrawn
                ↘ parse_failed → parsing
```

普通界面将内部状态简化为 `uploading`、`interpreting`、`ready`、`needs_attention` 和 `failed`。上传后自动完成解析与增强，不要求再次发送“本地解析”或“增强解析”请求。

“确认并发布”是结果页唯一主要发布动作。服务会在一次操作中完成最低发布检查以及必要的 `needs_review → ready_to_publish → published` 转换。最低条件为：

- 原始PDF仍可访问；
- 标题非空；
- 核心观点或主要正文至少一项非空；
- 报告日期为high confidence或已经人工确认；
- 不存在阻塞级unmapped/conflict。

行情日期和行情快照不是发布硬条件。发布幂等并记录操作人和时间；已发布内容修改会生成revision。撤回不删除原始PDF、审计或已冻结快照。
