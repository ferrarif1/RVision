# 当前执行清单（2026-03-13）

- Owner: Engineering
- Status: In Execution
- Last Updated: 2026-03-13 15:40 CST
- Scope: 基于当前代码和真实运行结果，对“已完成 / 当前主线 / 下一步”做一次收口盘点
- Supersedes: `platform_user_centric_execution_backlog_v1.md`
- Dynamic Todo: 日常持续推进优先维护 [dynamic_execution_todo_2026-03-11.md](./dynamic_execution_todo_2026-03-11.md)

## 1. 当前已打通的主链

- 训练控制面 MVP：
  - 训练作业创建、取消、重试、改派
  - 训练机器心跳
  - 待验证模型回收
  - readiness 展示
- 训练后验证主链：
  - 训练页可直达候选模型验证
  - 待验证模型可做任务级授权验证，不必先正式发布
- 模型审批 / 发布：
  - 审批工作台
  - 发布工作台
  - 流水线发布工作台
- 结果复核与回灌：
  - 结果页支持复核
  - 导出训练样本
  - 回灌训练中心
- 数据治理：
  - 设置页已有统一入口
  - 可预览、执行并记录审计
- 审批治理：
  - 已支持补材料、驳回、证据包导出

## 2. 当前唯一持续中的核心主线

### T5. OCR 真实泛化继续推进

当前这条主线已经不是“缺页面 / 缺接口 / 缺训练入口”，而是“缺更高占比的真实真值”。

#### 2.1 已到位的能力

- 车号规则已升级成规则族，不再只限固定 8 位数字。
- 巡检任务族已正式落地：
  - `car_number_ocr`
  - `inspection_mark_ocr`
  - `performance_mark_ocr`
  - `door_lock_state_detect`
  - `connector_defect_detect`
- 训练中心已接入巡检任务数据工作区。
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
- 风险治理已到位：
  - 审批工作台暴露 `proxy_truth_risk`
  - 默认阻止带代理真值继续正式训练
  - inspection OCR 已具备原图联看、CSV 预检查、CSV 导回、人工 review pack

#### 2.2 当前真实状态

- `inspection_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `suggestion_rows = 59`
  - `high_quality_suggestion_rows = 51`
  - `reviewed_rows = 9`
  - `manual_reviewed_rows = 3`
  - `proxy_seeded_rows = 6`
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

#### 2.3 当前真正阻断点

- inspection/performance OCR 不再缺工具链。
- 当前真正阻断点只剩：
  - 把 `proxy_seeded` 样本替换成真实 `final_text`
  - 让训练状态从 `cold_start_only` 推进到 `ready`
  - 再跑出更高真实真值占比的新训练作业与待验证模型

#### 2.4 结论

这是当前最核心、最影响业务价值的未完成项。

## 3. 其他未完成项的真实状态

### 3.1 错误提示模板

- 主链已收口。
- 剩余只是边角清理，不再是主线阻塞项。

### 3.2 数据保留策略

- 已前台化。
- 仍缺定时自动化和更细策略编排，但不阻塞主链。

### 3.3 训练 / 模型 / 流水线工作台

- 主体工作已完成。
- 剩余是细节统一和页面级收边，不是结构性缺口。

### 3.4 浏览器级人工走查

- 已有清单和首轮报告。
- 后续按页面边角问题持续补证据即可。

## 4. 接下来按顺序执行

### Step 1

- 继续推进 inspection/performance OCR 的真实真值替换。

### Step 2

- 替换后重新训练，并进入新一轮审批验证。

### Step 3

- 把 `door_lock_state_detect / connector_defect_detect` 拉进真实样本闭环。

## 5. 当前执行原则

- 优先修真实业务阻断，不优先继续加新展示层。
- 优先把 inspection/performance OCR 从“可冷启动训练”推进到“可正常训练”。
- 每完成一段就主动收口：
  - 更新动态待办
  - 更新相关业务/QA文档
  - 只保留当前真实状态
