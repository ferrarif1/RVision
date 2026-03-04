# References

这份文档记录当前文档体系升级时参考的公开方法论来源，用来解释为什么我们引入 `PRD / ADR / ORR / Release Gate / Accessibility` 这些治理结构。

## Product and Strategy

- AWS Prescriptive Guidance
  - `Start with why`
  - `PR/FAQ`
  - 用于约束产品文档从客户价值和目标旅程倒推，而不是先堆功能

## Architecture and Decision Records

- Continuous Architecture / ADR practice
  - 用于约束架构决策必须写清当前状态、决策驱动因素、备选方案与取舍

## Operational Readiness

- Google SRE
  - Production Readiness Review
  - 用于约束新能力上线前必须有可运维性、可靠性和责任准备度检查

## Accessibility and UX

- W3C WAI
  - Form instructions
  - WCAG techniques for labels and instructions
  - 用于约束表单说明、错误提示、可访问标签和输入帮助
- U.S. Web Design System (USWDS)
  - Design principles
  - Accessibility guidance
  - 用于约束“从真实用户需求出发”“把可访问性纳入全过程”“设计和实现要一起承担质量”

## How We Apply These References

这些参考不是拿来复制格式，而是用于建立本项目的质量门槛：

- 产品先定义问题、用户、路径、指标
- 架构先写 current vs target、decision drivers、rollback
- QA 先定义 evidence 与 release gate
- UI / Interaction 先保证可完成任务、可理解、可访问
