# 前端设计语言说明

## 1. 目标

本项目前端控制台采用“玻璃层次 + 高信息密度 + 低噪音交互”的设计方向，目标不是做营销站，而是做面向平台方、供应商、买家的工业级控制台。

核心视觉与交互原则参考：

- Apple Human Interface Guidelines
  - Liquid Glass
  - Foundations / Clarity / Deference / Depth
- Google Material Design 3
  - Hierarchy
  - Adaptive layouts
  - Motion with purpose
  - Color and state clarity

参考链接：

- https://developer.apple.com/design/human-interface-guidelines
- https://developer.apple.com/design/human-interface-guidelines/liquid-glass
- https://m3.material.io/

## 2. 当前落地原则

### 2.1 材质

- 主界面容器、侧栏、卡片、抽屉、状态条统一使用半透明玻璃面板
- 通过 `backdrop-filter + layered shadow + inner highlight` 建立空间层次
- 避免厚重纯色块，把信息区分主要交给材质、透明度、边界和间距

### 2.2 层级

- 一级：顶栏、主内容容器
- 二级：页面头、筛选区、功能卡片
- 三级：结果卡、指标卡、详情抽屉、表格行
- 所有交互反馈围绕“当前焦点最亮、非焦点退后”展开

### 2.3 交互

- 每个页面只保留一个最主要的主操作
- 任务流按“创建 -> 监控 -> 结果 -> 审计”拆页，避免一个页面承载过多任务
- 所有结果必须通过卡片、截图、状态标签、详情抽屉呈现，不直接暴露原始 JSON
- 列表页提供筛选、排序、分页，减少用户在长表格里迷失

### 2.4 动效

- Hover 只做轻微抬升、投影增强和边框高亮
- 加载反馈只做必要骨架和顶部进度条
- 通过 `prefers-reduced-motion` 自动降级动画

### 2.5 可读性

- 主字体优先使用 `SF Pro Text / Inter / PingFang SC`
- 数据字段、哈希、ID 使用等宽字体
- 保持暗色和亮色双主题可读性，不依赖单一颜色表达状态

## 3. 页面设计方法

### 工作台

- 先告诉用户“你是谁、你能做什么、下一步点哪里”
- 角色路径推荐比堆指标更重要

### 模型中心

- 以生命周期为主线：提交、审批、发布、回填任务
- 同时明确区分 `router` 与 `expert` 两类模型
- 平台拥有最终签名与发布控制权

### 流水线注册表

- 把主路由、专家映射、阈值和人工复核规则收敛在同一页
- 任务创建页默认从这里选择可调用 Pipeline

### 资产上传

- 强调分级、来源、后续用途
- 上传完成后立即给下一步 CTA

### 任务监控

- 核心是状态感知，不是表单
- 支持自动刷新和任务队列筛选

### 结果中心

- 核心是业务判断，不是技术原始数据
- 必须同时展示：结果字段、模型指纹、截图、告警

### 审计中心

- 核心是可追溯和可筛查
- 先给摘要指标，再给明细表格和详情抽屉

## 4. 后续继续演进方向

- 将静态前端继续拆分为真正的组件化工程
- 抽出统一玻璃组件：`GlassPanel / GlassButton / GlassDrawer / StatusBadge / MetricCard`
- 增加页面转场、空态插画和更细的响应式断点
- 让平台方、供应商、买家三类用户拥有更明显的独立首页
