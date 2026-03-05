# UI Track

## Mission

UI 轨道负责把产品和交互规范收敛成统一、克制、可扩展的设计系统。目标不是追求“炫”，而是让企业级平台在高信息密度下仍然稳定、清楚、可信。

## Design Principles

- 克制优先：先减少视觉噪音，再增加装饰。
- 层级清楚：颜色、间距、字号、边框只服务于信息优先级。
- 角色一致：不同角色能看到不同内容，但仍在同一设计系统里。
- 结果导向：用户应该更快理解“下一步做什么”而不是“界面有什么模块”。

## What UI Must Define

| Area | Must Define |
|---|---|
| Foundations | 色板、字体、间距、圆角、阴影、动效、栅格 |
| Components | Button、Input、Select、Table、Badge、Toast、Drawer、Modal、Empty State |
| States | hover、focus、active、disabled、error、success、warning |
| Content | 标题、描述、按钮、错误提示、帮助文案 |
| Accessibility | 对比度、键盘操作、aria、响应式、reduced motion |

## Component Quality Bar

一个组件进入共享设计系统前至少要满足：

- 有明确的使用场景和不该使用的场景。
- 有默认态、异常态、禁用态和加载态。
- 有无障碍要求和键盘行为。
- 有主次优先级定义，不允许“全都一样重要”。
- 已在至少一个真实页面中验证。

## Page Quality Bar

- 一个页面只有一个主 CTA。
- 标题区要说明当前页面价值，而不是技术模块名称。
- 空状态有下一步建议。
- 错误提示不甩锅给用户，也不暴露无意义内部术语。
- 视觉风格在首页、任务页、结果页之间一致。


## Console Interaction Baseline (2026-UI Refactor)

- 必须提供全局导航（Sidebar）和顶部用户菜单（Topbar）。
- 必须支持从任意子页面返回 Dashboard（导航、面包屑、返回按钮三重保障）。
- 必须具备统一状态组件：Loading Skeleton / Empty / Error，并覆盖列表页与详情页。
- 必须具备登录态完整闭环：Login、Logout、403、404。
- Devices 页面即使后端未接入也不能崩溃，需显示占位与下一步说明。

## Current Assets

- [../frontend_design_language.md](../frontend_design_language.md)
  当前前端设计语言与实现方向。
- [../templates/interaction_spec_template.md](../templates/interaction_spec_template.md)
  交互规格模板。

## Review Questions

- 用户是否一眼看出主次层级。
- 页面是否比上一个版本更短、更稳、更少噪音。
- 同一种状态是否在全站使用统一表达。
- 样式改变是否仍然服务于业务路径，而不是纯视觉变化。
