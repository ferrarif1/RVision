你是资深前端工程师与产品体验负责人。请对本仓库的前端做“平台控制台交互完整性”重构，优先解决：全局导航缺失、无法回到主页、缺少退出登录、交互混乱。

约束：
- 不引入 React/Vue 等大框架；保持当前结构：frontend/index.html + frontend/assets/app.js + frontend/assets/app.css
- 使用 hash router（location.hash）实现 SPA 路由
- 保持现有后端接口与 RBAC 能力（/auth/login、/users/me 返回 capabilities），前端仍需按 capabilities 控制可见菜单与页面访问权限
- UI 风格参考 Notion：浅色、低饱和、干净，按钮/卡片圆角，信息层级清晰

交付目标：
1) 实现 App Shell：
   - 左侧 Sidebar（主导航）
   - 顶部 Topbar（页面标题、Breadcrumb、右侧用户菜单）
   - 主内容区（页面渲染）
2) Sidebar 导航项（按角色能力动态显示）：
   - Dashboard, Assets, Tasks, Results, Models, Pipelines, Devices, Audit, Settings
3) Breadcrumb：
   - 根据路由自动生成，例如 #/models -> "Models"；#/models/123 -> "Models / Detail"
4) Back 机制：
   - Detail 页面左上角提供返回按钮（优先回到上一级列表页）
5) Logout：
   - Topbar 右侧用户菜单显示 username/role/tenant
   - 提供 Logout 按钮：清除 token 与用户缓存，跳转 #/login
6) 统一页面状态组件：
   - Loading Skeleton、Empty State（带行动按钮）、Error State（可重试）
   - 所有列表页与详情页统一使用
7) 路由与页面规范：
   - 统一路由表 routes = { path, component, requiredCapabilities }
   - 无权限访问返回 403 页面（提示无权限，提供回到 Dashboard 按钮）
   - 未匹配路由返回 404 页面
8) 必须新增 Devices 页面（即使是 MVP）：
   - 列表字段：device_id, buyer, status, last_heartbeat, agent_version
   - 若后端暂缺接口：先做占位页面与空态提示（“后端接口待接入”），不要让导航项点进去崩溃
9) 导航体验：
   - 当前页高亮
   - Sidebar 可折叠（可选）
   - 记住上次访问页面（localStorage）

实现步骤：
- 第一步：新增 frontend/assets/router.js（或在 app.js 内实现 router 模块）
- 第二步：新增 frontend/assets/layout.js：renderShell、renderSidebar、renderTopbar、renderBreadcrumb
- 第三步：将现有各页面渲染函数适配为 component(ctx) -> HTMLElement
- 第四步：在 /users/me 返回 capabilities 后构建导航与路由守卫
- 第五步：补齐 Login 页、403 页、404 页、Dashboard 页（可先简版）
- 第六步：在 CSS 中补齐 Notion 风格的基础组件（按钮、卡片、表格、抽屉、顶部栏、侧边栏、面包屑）

输出要求：
- 提交具体代码修改（新增/修改哪些文件、关键函数）
- 给出路由表、导航表、权限控制逻辑
- 确保进入任意子功能都可以回到 Dashboard（Sidebar + Breadcrumb + Back 三重保障）
- 不要把原始 JSON 直接铺满页面；默认以卡片/表格展示，JSON 放在 “Advanced” 折叠区域