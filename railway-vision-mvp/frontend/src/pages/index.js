export const pages = {
  login: () => `
    <section class="login-card">
      <h2>登录平台</h2>
      <p>请输入账号密码，进入四主线控制台。</p>
      <label>用户名</label><input id="username" value="platform_admin" />
      <label>密码</label><input id="password" type="password" value="platform123" />
      <button id="loginBtn">登录</button>
      <div class="hint">演示账号：platform_admin / supplier_demo / buyer_operator</div>
      <div id="loginMsg" class="hint"></div>
    </section>
  `,
  dashboard: () => `<h2>主页</h2><p>从左侧四条主线快速切换页面。</p>`,
  assets: () => `<h2>资产</h2><p>上传图片/视频并生成资产ID。</p>`,
  models: () => `<h2>模型</h2><p>提交候选模型并查看审批状态。</p>`,
  pipelines: () => `<h2>流水线</h2><p>管理路由与专家编排。</p>`,
  tasks: () => `<h2>任务</h2><p>创建任务并选择执行流水线。</p>`,
  results: () => `<h2>结果</h2><p>按任务ID查看结构化结果。</p>`,
  audit: () => `<h2>审计</h2><p>回查关键动作与导出记录。</p>`,
  devices: () => `<h2>设备</h2><p>查看设备在线与心跳状态。</p>`,
  settings: () => `<h2>设置</h2><p>管理个人偏好与租户设置。</p>`,
  403: () => `<h2>403</h2><p>你没有访问该页面权限。</p>`,
  404: () => `<h2>404</h2><p>页面不存在。</p>`,
};
