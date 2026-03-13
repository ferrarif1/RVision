# OCR 泛化迭代记录（2026-03-12）

本记录只写本轮面向“库内 45° 侧拍车身标记识别”场景的真实迭代，不写设想。

## 场景来源

参考文档：
- `/Users/zhangyuanyi/Downloads/北辆四足机器人/铁路货车轮足式机器人库内智能巡检应用技术方案.docx`

本轮提炼出的约束：
- 机器狗/轮足机器人沿车身侧面巡检，拍摄距离约 `1.5m–2m`
- 采集点常见视角为 `45° 斜角`
- 重点目标包括：
  - 车号
  - 定检标记
  - 性能标记
  - 门锁状态
  - 连接件缺陷
- OCR 主链应支持：
  - 文本区域检测
  - OCR 文本识别
  - 后续结构化解析扩展

## 本轮落地改动

代码：
- `edge/inference/pipelines.py`
- `config/car_number_rules.json`
- `config/ocr_scene_profiles.json`
- `config/railcar_inspection_task_catalog.json`

本轮补了 4 组能力：

1. 规则与任务族扩展
- 车号规则不再写死成“只能 8 位数字”
- 当前活动规则已升级成多规则族，接受：
  - 标准 8 位数字车号
  - 字母前缀数字编号
  - 紧凑型混合编号
- 巡检任务目录已正式扩成：
  - `car_number_ocr`
  - `inspection_mark_ocr`
  - `performance_mark_ocr`
  - `door_lock_state_detect`
  - `connector_defect_detect`

2. 场景配置外置
- 新增 `ocr_scene_profiles.json`
- 当前激活配置：`railcar_yard_side_view_v1`
- 已预留目标：
  - `car_number`
  - `inspection_mark`
  - `performance_mark`

3. 45° 侧拍 OCR 救援
- 文字带搜索区域改为可配置
- OCR 预处理新增：
  - `clahe`
  - `sharpen`
  - `top_hat`
  - `rectified / rectified_otsu / rectified_inv`
- 新增文本带旋转矫正变体，优先应对侧拍、斜角和轻透视

4. 更稳的有效候选接受逻辑
- 对合法 8 位数字候选放宽“直接接受”的门槛
- 对规则拒绝后的高分候选增加二阶段扩框重扫
- 对明显截断的 7 位数字候选增加“超宽扩框救援”

## 本轮本地难样本探针

说明：
- 关闭 curated/fixture 快捷命中
- 直接在运行中的 `vistral_edge_agent` 容器里调用 `_run_car_number_ocr`

结果：

| source_file | gt | runtime_text | engine | 结论 |
| --- | --- | --- | --- | --- |
| `2477_104_1...jpg` | `64507965` | `null` | `ocr_rule_rejected` | 仍失败 |
| `2216_104_0...jpg` | `65115222` | `null` | `ocr_rule_rejected` | 仍失败 |
| `3542_104_0...jpg` | `61172052` | `null` | `ocr_rule_rejected` | 仍失败 |
| `6775_104_1...jpg` | `60460284` | `60460282` | `tesseract:clahe` | 可读但末位错误 |
| `9664_104_0...jpg` | `62745500` | `62745500` | `tesseract:clahe` | 正确 |

随后又补了一轮“滑窗条带 + 投影细分”救援，本地复跑 3 张最难样本：

| source_file | gt | runtime_text | engine | 结论 |
| --- | --- | --- | --- | --- |
| `2477_104_1...jpg` | `64507965` | `null` | `ocr_rule_rejected` | 仍失败 |
| `2216_104_0...jpg` | `65115222` | `35152220` | `tesseract:clahe:psm6` | 从空结果提升为可读，但仍错号 |
| `3542_104_0...jpg` | `61172052` | `null` | `ocr_rule_rejected` | 仍失败 |

再随后补了“合法 8 位结果稳定性判别”，重新复跑 `2216 / 6775 / 9664`：

| source_file | gt | runtime_text | engine | 结论 |
| --- | --- | --- | --- | --- |
| `2216_104_0...jpg` | `65115222` | `null` | `ocr_rule_rejected` | 已从错号拉回为拒绝输出 |
| `6775_104_1...jpg` | `60460284` | `60460282` | `tesseract:clahe` | 仍差 1 位 |
| `9664_104_0...jpg` | `62745500` | `62745500` | `tesseract:clahe` | 仍保持正确 |

## 当前判断

这轮迭代是“有进展，但没有收口”：
- 已把 OCR 场景能力正式对齐到“库内 45° 侧拍车身标记识别”的方向
- 已把车号规则和巡检任务目录扩成机器人场景可持续演进的基础设施
- 已确认当前主链对至少一部分陌生样本可直接读出合法 8 位车号
- 但 `2477 / 2216 / 3542` 这类难样本仍然会停在 `ocr_rule_rejected`
- 其中 `2216` 已从“错误放出合法 8 位”拉回为“安全拒绝”，说明稳定性判别是必要的

从候选池看，当前剩余难点主要是：
- 只读出 6–7 位截断数字
- 读出高分垃圾串，但没有稳定拉回 8 位合法车号
- 侧拍 ROI 虽然更稳了，但对“弱对比 + 脏污 + 透视压缩”的恢复还不够
- 一旦滑窗救援过强，会出现“读出合法 8 位，但并不是真值”的假阳性，需要补字符级稳定性约束
- 当前下一步的重点已经从“继续放大 ROI”转成“字符级纠错 + 假阳性抑制”

## 下一轮重点

下一轮不再泛泛调阈值，优先做：
- 候选池级别的“位数补偿 / 近似合法序列”救援
- 进一步提高侧拍 ROI 的展宽与定位质量
- 给“合法但可疑”的 8 位结果补稳定性判别，避免把假阳性直接当成成功
- 扩更正式的真实 probe，不只看单图成功与否，还看：
  - `empty`
  - `rule_rejected`
  - `ground_truth_mismatch`
  - `low_confidence`
- 在 `inspection_mark_ocr / performance_mark_ocr / door_lock_state_detect / connector_defect_detect` 上启动首版数据采集与训练
