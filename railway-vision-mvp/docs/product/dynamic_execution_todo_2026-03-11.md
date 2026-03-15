# 动态待办清单（2026-03-14）

- Owner: Engineering
- Status: In Execution
- Last Updated: 2026-03-14 13:05 CST
- Scope: 当前真实执行面板。只保留“仍未完成 / 正在推进 / 已验证完成”的事项。
- Source of Truth:
  - [当前真实执行盘点](./current_execution_backlog_2026-03-10.md)
  - [真实运行审计](../qa/live_chain_audit_2026-03-10.md)
  - [页面级走查清单](../qa/browser_walkthrough_checklist_2026-03-11.md)
  - [巡检任务数据工作区](./railcar_inspection_data_workspace_2026-03-12.md)
  - [智能引导 / LLM 工作台](./intelligent_guide_llm_workbench_2026-03-14.md)

## 使用规则

- 新需求先记入本文件，再决定是否插队。
- 每完成一段独立工作，主动收口：
  - 更新本清单
  - 更新相关业务/QA文档
  - 标记完成项为删除线
- 只记录当前真实能力，不保留重复里程碑和过时状态。
- 智能引导 / LLM 只能做“建议、预填、导航、可选自动调整”，不能取代手动控制。
- 任何涉及模型、代码、参数、训练规格的自动调整，都必须保留显式人工编辑入口。

## 当前平台状态

- 平台主链已可运行：
  - 资产上传
  - 任务创建 / 快速识别
  - 结果回传 / 复核 / 回灌
  - 训练作业 / 训练机器
  - 待验证模型 / 审批 / 发布
  - 边缘执行 / 审计
- 高复杂页面已完成：
  - 页内导航
  - 默认视图减负
  - 技术详情后置
- 高优先级错误提示模板已完成结构化统一。
- 数据治理已前台化。
- 审批治理已补齐补材料 / 驳回 / 证据包。
- 当前唯一持续中的核心主线：`T5 OCR 真实泛化继续推进`。

## 已完成的核心任务

### ~~T1. 全站控制台页继续去技术噪音~~

- Priority: P0
- Status: Done
- Result:
  - ~~训练 / 模型 / 流水线 / 任务 / 结果 / 资产 / 审计 / 首页 / 车号文本复核完成页内导航化~~
  - ~~默认视图优先显示状态、下一步动作、业务摘要~~
  - ~~长 ID / hash / 内部状态后置到 `技术详情`~~
  - ~~统一玻璃层、渐变光晕、悬停反馈和选中态~~

### ~~T2. 页面级人工走查制度化~~

- Priority: P0
- Status: Done
- Result:
  - ~~关键页走查清单建立~~
  - ~~首轮走查报告沉淀~~

### ~~T2b. 新用户视角的术语与流程减负~~

- Priority: P0
- Status: Done
- Result:
  - ~~默认可见区高频术语已改成人话~~
  - ~~高频主路径已进一步收成单一路径~~
  - ~~`asset_id / task_id / worker / model_id` 默认已转成业务语言~~

### ~~T3. 任务页 / 结果页页面级收边~~

- Priority: P1
- Status: Done
- Result:
  - ~~任务页、结果页完成一级导航 + 二级导航自动切换~~
  - ~~长文本、长版本号、长 ID 溢出系统性修复~~
  - ~~结果查询后可自动跳到更合适的结果分区~~

### ~~T4. 统一错误提示模板~~

- Priority: P1
- Status: Done
- Result:
  - ~~任务 / 结果 / 训练 / 模型 / 流水线 / 资产 / 边缘执行主链统一结构化错误~~
  - ~~前端统一按 `code / message / next_step` 展示~~

### ~~T6. 数据保留策略产品化~~

- Priority: P2
- Status: Done
- Result:
  - ~~设置页新增 `数据治理` 工作区~~
  - ~~支持预览、执行、权限和审计~~

### ~~T7. 审批治理补全~~

- Priority: P2
- Status: Done
- Result:
  - ~~要求补材料~~
  - ~~驳回模型~~
  - ~~导出证据包~~

### ~~T8. 智能引导 / LLM 入口~~

- Priority: P1
- Status: Done
- Result:
  - ~~新增独立 `智能引导` 入口，不再把“上传图片、选模型、问下一步”硬塞进任务页~~
  - ~~支持 `API 模式 / 本地模型模式` 两种入口~~
  - ~~平台内置精选 10 个开源本地模型，并支持直接下载 / 查看下载任务 / 取消下载~~
  - ~~用户输入目标、资产、模型或任务类型后，可直接获得下一步引导：任务验证 / 训练准备 / 审批 / 发布~~
  - ~~跨页面动作支持预填参数和跳转，不需要用户自己重新找入口~~

## 当前唯一持续主线

### T5. OCR 真实泛化继续推进

- Priority: P1
- Status: In Progress
- Why:
  - 当前最影响业务价值的剩余核心能力缺口。
  - 识别对象已不只限车号，已扩成正式巡检任务族。

#### T5-A. 已经做完的部分

- 车号规则已升级成规则族：
  - 标准 8 位数字
  - 字母前缀数字编号
  - 紧凑型混合编号
- 巡检任务族已落地：
  - `car_number_ocr`
  - `inspection_mark_ocr`
  - `performance_mark_ocr`
  - `door_lock_state_detect`
  - `connector_defect_detect`
- 训练中心已接入巡检任务数据工作区：
  - 建议样本量
  - 拍摄距离 / 角度 / 图像要求
  - 验收目标
  - 结构化字段建议
- inspection/performance OCR 已具备：
  - 工作区模板
  - 代理裁剪
  - 自动建议
  - 高质量建议优先复核
  - 通用复核页
  - 训练包导出
  - 导出训练资产
  - 直接创建训练作业
  - 待验证模型回收
  - 审批工作台可见
- inspection/performance OCR 风险治理已到位：
  - 审批工作台暴露 `proxy_truth_risk`
  - 默认阻止带代理真值继续正式训练
  - 只有显式允许“仅冷启动继续训练”才放行
- inspection OCR 人工替换工具链已补齐：
  - 原图联看
  - 代理替换队列 CSV 导出
  - 高质量建议队列 / review pack 导出
  - 高质量建议批量预检查 / 批量确认
  - 预检查 CSV 导入
  - CSV 导回
  - 人工替换工作包 ZIP

#### T5-B. 当前真实状态

- `inspection_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `suggestion_rows = 59`
  - `high_quality_suggestion_rows = 51`
  - `high_quality_review_candidate_rows = 51`
  - `reviewed_rows = 9`
  - `manual_reviewed_rows = 3`
  - `proxy_seeded_rows = 6`
  - `proxy_replacement_samples = 6`
  - `training_readiness.status = cold_start_only`
- `performance_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `suggestion_rows = 57`
  - `high_quality_suggestion_rows = 45`
  - `reviewed_rows = 9`
  - `manual_reviewed_rows = 3`
  - `proxy_seeded_rows = 6`
  - `training_readiness.status = cold_start_only`
- inspection/performance OCR 已完成至少一轮真实训练闭环：
  - 训练作业 `SUCCEEDED`
  - 新模型 `SUBMITTED`
  - 审批工作台可见
- inspection OCR 高质量建议批量确认已真实 smoke：
  - `preview-accept-high-quality -> would_update_rows = 1`
  - `accept-high-quality -> updated_rows = 1`
  - 验证后已恢复工作区文件，不污染当前数据基线

#### T5-C. 当前真正阻断点

- inspection/performance OCR 不再缺：
  - 页面
  - 接口
  - 导出
  - 训练入口
  - 审批入口
- 当前真正阻断点只剩：
  - 还需要把 `proxy_seeded` 样本替换成真实 `final_text`
  - 让 inspection/performance OCR 从“仅冷启动可训练”推进到“可正常训练”

#### T5-D. 完成标准

- inspection/performance OCR 的 `proxy_seeded_rows` 明显下降
- `manual_reviewed_rows` 明显上升
- `training_readiness.status` 从 `cold_start_only` 推进到 `ready`
- 再跑出至少一轮更高真实真值占比的新训练作业与待验证模型
- 审批工作台中的 `proxy_truth_risk` 比例下降或治理说明转弱

#### T5-E. 关键证据

- `edge/inference/pipelines.py`
- `config/car_number_rules.json`
- `config/ocr_scene_profiles.json`
- `config/railcar_inspection_task_catalog.json`
- `config/railcar_inspection_dataset_blueprints.json`
- `backend/app/api/training.py`
- `frontend/src/pages/index.js`
- `docker/scripts/prepare_inspection_ocr_proxy_crops.py`
- `docker/scripts/generate_inspection_ocr_suggestions.py`
- `docker/scripts/seed_inspection_ocr_from_car_number_truth.py`
- `docs/product/railcar_inspection_data_workspace_2026-03-12.md`
- `docs/qa/live_chain_audit_2026-03-10.md`

## 下一步自动执行

### N1. inspection/performance OCR 真实真值替换

- Priority: P1
- Status: Next
- Why:
  - 当前唯一真正阻断 inspection/performance OCR 继续迈进的就是 `proxy_seeded` 样本仍未替换完。
  - 系统现在已经会明确告诉用户：先处理训练阻断样本，处理完后预计可直接进入 `ready`。
- Done When:
  - `inspection_mark_ocr.proxy_seeded_rows < 6`
  - `performance_mark_ocr.proxy_seeded_rows < 6`
  - `manual_reviewed_rows` 明显上升
  - 至少完成一轮新的真实 `final_text` 导入

### N2. inspection/performance OCR 下一轮训练与审批验证

- Priority: P1
- Status: Next
- Why:
  - 只有替换真值后重新训练，才能验证风险是否真正下降。
- Done When:
  - 新训练作业 `SUCCEEDED`
  - 新待验证模型入库
  - 审批工作台里 `proxy_truth_risk` 弱化或数据比例下降

### N4. 智能引导保留人工控制与可选自动调整

- Priority: P1
- Status: In Progress
- Why:
  - 智能引导已经成为正式入口，但不能演变成黑箱代理。
  - 用户明确要求：LLM 自动调整是可选项，必须同时保留手动调整模型、代码、参数的能力。
- Scope:
  - 智能引导页明确区分：
    - 仅给建议
    - 自动预填
    - 可选自动调整
  - 训练、任务、模型、流水线相关跳转页必须保留：
    - 手动选模型
    - 手动改参数
    - 手动改代码 / 算法配置
  - 自动调整过的内容要可见、可撤销、可改写
- Done When:
  - 智能引导页与后续承接页都明确存在手动入口
  - 自动生成的参数 / 代码 / 配置会带来源标记
  - 用户可以在提交前显式覆盖和撤销

### ~~N3. door_lock_state_detect / connector_defect_detect 进入真实样本闭环~~

- Priority: P2
- Status: Done
- Result:
  - ~~door_lock_state_detect 已保留 2 条真实样本，`reviewed_rows = 2`~~
  - ~~connector_defect_detect 已保留 2 条真实样本，`reviewed_rows = 2`~~
  - ~~两类任务的 `training_readiness.status` 都已从 `blocked` 推进到 `ready`~~
  - ~~两类任务都已跑出首条真实训练作业，并成功回收到待验证模型~~

## 最近完成

### D67. 智能引导 / LLM 工作台进入正式产品能力

- Status: Done
- Result:
  - `GET /assistant/provider-modes`
  - `GET /assistant/local-models`
  - `GET /assistant/local-models/download-jobs`
  - `POST /assistant/local-models/download`
  - `POST /assistant/local-models/download-jobs/{job_id}/cancel`
  - `POST /assistant/plan`
  已在运行环境中真实验证通过。
  - 本地模型目录已内置精选 10 个开源模型。
  - 智能引导页已可根据目标、资产、模型、任务类型给出主推荐动作和次推荐动作。

### D80. 智能引导默认切回人工控制优先

- Status: Done
- Result:
  - 智能引导新增 `执行方式`
  - 默认是 `仅导航，不改字段`
  - `跳转并带建议过去` 改成显式可选
  - 任务页、训练页、模型页已显示“来自智能引导的可编辑建议 / 模型定位”
  - 承接页已支持：
    - 一键清空建议
    - 返回智能引导
    - 明确提示“仍可手动修改模型、参数、代码配置”

### D82. 全站新增 ChatGPT 清透白 / 夏日奶油色主题

- Status: Done
- Result:
  - 顶栏新增全局主题切换：
    - `夜幕金`
    - `ChatGPT 清透白`
    - `夏日奶油色`
  - 智能引导页已重构成：
    - 对话优先主舞台
    - 右侧上下文抽屉
    - 底部统一输入区
  - 智能引导页内主题切换已改成作用于全站，而不是只限本页

### D68. inspection/performance OCR 代理裁剪与自动建议覆盖率提升

- Status: Done
- Result:
  - `inspection_mark_ocr.suggestion_rows = 59`
  - `performance_mark_ocr.suggestion_rows = 57`

### D69. inspection/performance OCR 建议质量分层与优先复核队列

- Status: Done
- Result:
  - `inspection_mark_ocr.high_quality_suggestion_rows = 51`
  - `performance_mark_ocr.high_quality_suggestion_rows = 45`

### D70. inspection OCR 训练前判断产品化

- Status: Done
- Result:
  - 后端与前端都已直接显示：
    - `可正常训练`
    - `仅冷启动可训练`
    - `仍不可导出`

### D71. inspection OCR 人工替换工具链收口

- Status: Done
- Result:
  - 原图联看
  - 代理替换队列导出
  - 高质量建议包导出
  - 预检查 CSV
  - CSV 导回
  - review pack 导出

### D72. inspection 工作区摘要刷新机制补齐

- Status: Done
- Result:
  - 新增 `refresh_inspection_workspace_summaries.py`
  - `summary.json` 可从当前 `manifest.csv` 重建
  - 已刷新两类 OCR 工作区摘要到真实状态

### D73. 状态类巡检任务进入正式复核 / 导出 / 训练入口

- Status: Done
- Result:
  - `door_lock_state_detect / connector_defect_detect` 已新增正式状态复核页
  - 已支持：
    - 工作区摘要
    - 样本列表
    - crop / 原图查看
    - 状态标签保存
    - 导出训练包
    - 导出训练资产
    - 直接创建训练作业
  - 当前真实状态仍为：
    - `row_count = 0`
    - `training_readiness.status = blocked`
  - 说明这两类任务已不再卡在产品工具链，而只剩真实样本采集与标注

### D74. 状态类巡检任务支持从现有真实资产导入工作区

- Status: Done
- Result:
  - 新增 `POST /training/inspection-state/{task_type}/import-assets`
  - 状态复核页新增：
    - `导入现有资产`
    - 最近图片资产建议
  - 真实 smoke 已通过：
    - `door_lock_state_detect` 成功导入 1 张现有图片资产
    - `summary.row_count` 从 `0` 临时提升到 `1`
    - `items.total = 1`
  - 验证后已回滚工作区文件并刷新摘要，当前基线仍保持 `row_count = 0`

### D75. 状态类巡检任务支持离线批量复核

- Status: Done
- Result:
  - 新增：
    - `GET /training/inspection-state/{task_type}/export-review-queue`
    - `GET /training/inspection-state/{task_type}/export-review-pack`
    - `POST /training/inspection-state/{task_type}/preview-import-reviews`
    - `POST /training/inspection-state/{task_type}/import-reviews`
  - 状态复核页新增：
    - `导出状态复核队列`
    - `导出人工复核包`
    - `预检查离线复核 CSV`
    - `导入离线复核 CSV`
  - 真实 smoke 已通过：
    - review queue 导出 `200 text/csv`
    - review pack 导出 `200 application/zip`
    - 预检查返回 `would_update_rows = 1`
    - 正式导入返回 `updated_rows = 1`
  - 验证后已恢复 door_lock_state_detect 工作区文件并刷新摘要，当前基线仍保持 `row_count = 0`

### D76. 状态类巡检任务接入优先复核样本与训练就绪判断

- Status: Done
- Result:
  - `inspection-workspaces/summary` 里的状态类任务已返回：
    - `starter_samples`
    - `training_readiness`
  - 状态复核页摘要区已显示：
    - 建议采集条件
    - 优先复核样本
    - 训练就绪判断
  - 真实 smoke 已通过：
    - 临时导入 1 张 `door_lock_state_detect` 图片资产后
    - `summary.row_count = 1`
    - `starter_samples_count = 1`
    - `training_readiness.status = blocked`
  - 验证后已恢复工作区文件并刷新摘要，不污染当前基线

### D77. 状态类巡检任务进入首条真实训练作业闭环

- Status: Done
- Result:
  - `door_lock_state_detect`
    - `row_count = 2`
    - `reviewed_rows = 2`
    - `training_readiness.status = ready`
    - 首条真实训练作业：`train-bbab47f859`
    - 待验证模型：`door_lock_state_detect:v20260313.085312.fb88`
  - `connector_defect_detect`
    - `row_count = 2`
    - `reviewed_rows = 2`
    - `training_readiness.status = ready`
    - 首条真实训练作业：`train-80b794db2e`
    - 待验证模型：`connector_defect_detect:v20260313.085554.827f`

### D78. 本机训练机器恢复并重新承接真实训练作业

- Status: Done
- Result:
  - `local-train-worker` 已恢复 `ACTIVE`
  - `door_lock_state_detect` 与 `connector_defect_detect` 的首条真实训练作业均由本机训练机器完成

### D79. inspection/performance OCR 增加训练阻断样本工作流

- Status: Done
- Result:
  - inspection/performance OCR 现在把“当前真正阻断正式训练的样本”独立成正式工作流：
    - `readiness_blocker_rows`
    - `readiness_blocker_samples`
  - 后端新增：
    - `GET /training/inspection-ocr/{task_type}/export-readiness-blocker-queue`
    - `GET /training/inspection-ocr/{task_type}/export-readiness-blocker-pack`
  - 前端新增：
    - `仅看训练阻断样本`
    - `优先处理训练阻断样本`
    - `导出训练阻断队列`
    - `导出训练阻断包`
  - 当前真实 smoke：
    - `inspection_mark_ocr.readiness_blocker_rows = 6`
    - `inspection_mark_ocr.readiness_blocker_samples = 6`
    - 训练中心工作区卡片已同步回显相同数量

### D80. inspection/performance OCR 增加训练就绪行动计划

- Status: Done
- Result:
  - inspection/performance OCR 摘要与训练中心工作区卡片现在会返回并显示：
    - `readiness_action_plan.title`
    - `readiness_action_plan.summary`
    - `projected_status_after_blockers`
    - `projected_manual_reviewed_rows`
    - `remaining_manual_rows_after_blockers`
  - `inspection_mark_ocr` 当前真实行动计划已明确：
    - `title = 先处理训练阻断样本`
    - `projected_status_after_blockers = ready`
    - `projected_manual_reviewed_rows = 9`
  - 同时统一修正了 `high_quality_review_candidate_rows` 口径：
    - 现在 summary 和工作区卡片都返回真实总数 `51`
    - 不再混用“预览样本数 8”冒充总量

### D81. inspection/performance OCR 增加训练阻断样本一键批量处理

- Status: Done
- Result:
  - inspection/performance OCR 现在不只会导出训练阻断样本，还能直接批量预检查和处理：
    - `POST /training/inspection-ocr/{task_type}/preview-resolve-readiness-blockers`
    - `POST /training/inspection-ocr/{task_type}/resolve-readiness-blockers`
  - 前端新增：
    - `预检查阻断样本处理`
    - `批量处理训练阻断样本`
  - live smoke：
    - `inspection_mark_ocr` 前 2 条阻断样本预检查：
      - `would_update_rows = 2`
      - `resolved_reasons = [proxy_seeded_truth]`
    - 正式处理后：
      - `updated_rows = 2`
      - `proxy_seeded_rows: 6 -> 4`
      - `manual_reviewed_rows: 3 -> 5`
      - `readiness_blocker_rows: 6 -> 4`
    - 验证后已恢复工作区文件并刷新摘要，不污染当前基线

## 执行原则

- 优先做真实阻断，不优先做新的展示层花样。
- 优先把 inspection/performance OCR 从“有工具”推进到“有真实真值、可正常训练”。
- 完成一段就主动收口：
  - 更新本清单
  - 更新相关文档
  - 删除线标记完成项
