# 铁路货车轮足机器人巡检模型族设计（2026-03-12）

- Owner: Engineering / Product
- Status: In Progress
- Last Updated: 2026-03-12
- Scope:
  - 将《铁路货车轮足式机器人库内智能巡检应用技术方案》中的识别目标收敛为平台可执行的模型族、训练计划与任务目录
- Non-goals:
  - 本文不代表这些模型已经全部训练完成
  - 本文不替代现场采集、标注规范和验收方案

## 1. 场景来源

来源文档明确了机器狗 / 轮足机器人在库内巡检时的主要 AI 识别目标：

- 车号
- 定检标记
- 性能标记
- 门锁状态
- 连接件缺陷

同时给出了关键工程约束：

- 典型采集角度：沿车身一侧 1.5m-2m 距离、约 45° 斜角拍摄
- 文字识别类初始训练样本：不少于 200 张
- 门锁 / 连接件类缺陷识别初始训练样本：不少于 500 张
- 单张图像文字识别耗时目标：`<= 0.5s`
- 单张图像缺陷分析平均耗时目标：`<= 1.0s`

## 2. 推荐模型族

### 2.1 文字类 OCR 模型族

建议统一为一个“文字区域检测 + 多任务解码”的 OCR 家族，而不是每种文字都完全独立训练：

1. `car_number_ocr`
   - 目标：车身车号、车体编号
   - 输出：文本 + 定位框 + 规则匹配结果
   - 当前优先级：最高

2. `inspection_mark_ocr`
   - 目标：定检标记、检修记录、定检日期
   - 输出：文本 + 可选结构化字段
   - 当前优先级：中高

3. `performance_mark_ocr`
   - 目标：性能标记、性能代码、能力文字
   - 输出：文本 + 可选结构化字段
   - 当前优先级：中

推荐工程策略：

- 共享同一套文字区域检测主干
- 车号、定检标记、性能标记分别做轻量头部或解码头
- 先做通用文本区域定位，再按任务类型调用不同规则或词表

## 3. 缺陷识别模型族

### 3.1 门锁状态识别

- 推荐任务编码：`door_lock_state_detect`
- 建议输出：
  - `locked`
  - `open`
  - `uncertain`
- 推荐模型形态：
  - 先目标检测定位门锁区域
  - 再做二分类 / 三分类状态判断

### 3.2 连接件缺陷识别

- 推荐任务编码：`connector_defect_detect`
- 建议输出：
  - `normal`
  - `loose`
  - `deformed`
  - `missing`
  - `uncertain`
- 推荐模型形态：
  - 目标检测 + 缺陷分级
  - 后续可追加语义分割，提升轻微缺陷定位能力

## 4. 训练优先级

按工程投入与业务价值排序，建议分三阶段推进：

### P0

- `car_number_ocr`
- 目标：
  - 先把库内 45° 侧拍车号泛化能力收口
  - 建立多规则编号校验，不再假设只可能是 8 位纯数字

### P1

- `inspection_mark_ocr`
- `door_lock_state_detect`
- 目标：
  - 把文字类与状态类场景都覆盖到，形成机器人巡检最小可用闭环

### P2

- `performance_mark_ocr`
- `connector_defect_detect`
- 目标：
  - 形成完整库内车身文字 + 关键部件识别族

## 5. 数据采集与标注建议

### 5.1 OCR 类

- 每类文字至少 `200` 张起步，建议 `500+`
- 必须覆盖：
  - 光照强弱变化
  - 轻度污渍 / 锈蚀
  - 斜拍透视
  - 局部遮挡
  - 不同字体、字号、底色

标注建议：

- `bbox`
- `text`
- `task_type`
- 可选结构化字段（如日期、车型代码）

### 5.2 门锁 / 连接件类

- 每类至少 `500` 张起步，建议 `1000+`
- 要同时采：
  - 正常样本
  - 明显异常样本
  - 边界模糊样本
- 对轻微缺陷建议单独打 `uncertain`，避免训练时标签噪音过大

## 6. 当前仓库落地点

本轮已经落地的基础设施：

- 车号规则从单一 8 位数字升级为“多规则族”
- 新增任务目录配置：
  - `config/railcar_inspection_task_catalog.json`
- OCR 场景配置已与库内 45° 侧拍场景对齐：
  - `config/ocr_scene_profiles.json`
- 巡检任务数据蓝图已写入采集约束、推荐样本量与首版验收目标：
  - `config/railcar_inspection_dataset_blueprints.json`
- 平台任务标签和意图路由已扩展：
  - `car_number_ocr`
  - `inspection_mark_ocr`
  - `performance_mark_ocr`
  - `door_lock_state_detect`
  - `connector_defect_detect`
- 训练中心已新增首版训练预设，能直接为上述任务族生成基础训练参数模板
- 新增工作区初始化脚本：
  - `docker/scripts/bootstrap_inspection_labeling_workspace.py`
- 新增训练/验证包生成脚本：
  - `docker/scripts/build_inspection_task_dataset.py`
- 仓库内已生成首批空工作区模板：
  - `demo_data/generated_datasets/inspection_mark_ocr_labeling/`
  - `demo_data/generated_datasets/performance_mark_ocr_labeling/`
  - `demo_data/generated_datasets/door_lock_state_detect_labeling/`
  - `demo_data/generated_datasets/connector_defect_detect_labeling/`
- 训练中心已可直接展示上述 4 个工作区的数据准备度、场景约束与验收目标

## 7. 下一步

1. 按上述任务族补真实数据采集和标注
2. 优先继续收口 `car_number_ocr` 真泛化
3. 基于当前工作区模板新建 `inspection_mark_ocr` 和 `door_lock_state_detect` 的首版真实训练集
4. 再进入候选模型验证、审批与发布
