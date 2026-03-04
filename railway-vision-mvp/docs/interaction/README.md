# Interaction Track

## Mission

Interaction 轨道负责把 PRD 落成一套可以直接实现与测试的行为契约，包括页面结构、流程步骤、状态反馈、异常处理和内容策略。

## Scope

这个轨道关注“用户如何完成任务”，而不是“后端怎么实现”：

- 页面层级与信息优先级
- 表单结构与默认值
- 空状态 / 加载态 / 错误态 / 无权限态
- 跳转逻辑、成功反馈、回退路径
- 文案与动作命名

## Interaction Contract

每个关键页面都应当定义：

| Layer | Must Have |
|---|---|
| 标题区 | 当前页面目的、当前角色可做什么 |
| 主行动区 | 1 个主动作，必要字段和默认值 |
| 辅助区 | 次要筛选、上下文信息、最近记录 |
| 结果区 | 成功结果、状态摘要、下一步入口 |
| 帮助区 | 高级说明、边界条件、术语提示 |

## State Design Bar

关键流程至少覆盖以下状态：

- `empty`
- `loading`
- `success`
- `partial success`
- `error`
- `permission denied`
- `stale / outdated`

每个状态都必须包含：

- 当前发生了什么
- 用户下一步做什么
- 是否可重试
- 是否需要联系谁

## Quality Bar

- 主路径不超过 3 步。
- 主按钮只有 1 个，次按钮不超过 2 个。
- 必填项明确，默认值合理。
- 提交失败时能定位到字段或动作。
- 同一动作在不同页面使用统一名称。

## Artifacts

- 关键流程说明
- 页面线框 / 结构表
- 状态矩阵
- 交互 spec
- 文案规范与错误提示规范

推荐模板：

- [../templates/interaction_spec_template.md](../templates/interaction_spec_template.md)
- [../templates/prd_template.md](../templates/prd_template.md)

## Review Questions

- 用户是否知道自己当前在哪一步。
- 成功后是否自然进入下一步，而不是被迫跳页寻找。
- 没有数据时，页面是否仍然有明确价值。
- 出错时是否告诉用户该怎么继续。
