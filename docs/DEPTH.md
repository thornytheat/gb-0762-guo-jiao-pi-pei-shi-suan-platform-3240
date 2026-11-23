# 深度登记 果胶批配试算台

- 规模：中型
- 核心规则：离散称量同时验湿重、干重与凝胶区间，先最少批再裁决到期先后。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 批次化验采信 | 扫描原件与冲突 | POST /api/assay | `app/modules/assay/service.py` | `tests/test_assay.py` |
| M2 干物折算 | 检查过期与干物库存 | POST /api/dry | `app/modules/dry/service.py` | `tests/test_dry.py` |
| M3 目标区间验方 | 输入提案并查约束 | POST /api/formula | `app/modules/formula/service.py` | `tests/test_formula.py` `tests/test_plan_contract.py` |
| M4 整数配料寻优 | 按称量刻度求组合 | POST /api/blend | `app/modules/blend/search.py` | `tests/test_blend.py` `tests/test_solver_oracle.py` |
| M5 领用与余量核算 | 核对库存、领用和缺口 | POST /api/stock | `app/modules/stock/balance.py` | `tests/test_stock.py` |
| M6 批次留档复跑 | 留档并验证重复提交 | POST /api/batches | `app/modules/batches/storage.py` | `tests/test_batches.py` |
| M7 试配凭据签发 | 复核门槛、签发/撤回/下载 | POST/GET /api/credentials | `app/modules/credentials/service.py` | `tests/test_credentials.py` |

## 凭据最小数据（客户可独立复算，车间不泄密）

旧版签发附整份留档，会泄露逐批化验、库存与批号。现行凭据只给**聚合值 + 计划约束 + 判定结果**，客户据此即可在凝胶下限附近独立复算，无需任何批号级数据：

| 凭据字段 | 内容 | 客户复算用途 |
|---|---|---|
| `plan.target_g` / `step_g` | 计划量、领用刻度（克） | 称量门槛 `mass_g == target_g` |
| `plan.dry_min_g` | 干物下限（克） | 干物门槛 `dry_u ≥ dry_min_g × 10000` |
| `plan.gel_low_sag` / `gel_high_sag` | 凝胶上下限（SAG，含界） | 凝胶门槛（整数叉乘，无浮点） |
| `totals.mass_g` | 实际领用总湿重 | 称量核对 |
| `totals.dry_u` / `dry_g` | 总干物（万分克整数 / 克展示） | 干物核对 |
| `totals.gel_moment` / `gel_sag` | 总凝胶矩（整数串）/ SAG 展示值 | 凝胶核对 |
| `reconcile` | 对账布尔与缺口克数 | 领用对账核对 |
| `checks` / `blocking` | 五项门槛结论与阻断码 | 判定复核 |
| `scales` | 整数比例（SAG×1000、干物×10000） | 复算单位换算 |
| `assay_sha256` / `credential_id` | 化验源摘要、凭据内容哈希 | 溯源与防篡改 |

**明确不给**：批号、原件行号、逐批水分/凝胶度/库存/到期日、寻优分配、隔离行原值；`counts` 只给采信批数与隔离行数两个计数。

客户复算公式（全部整数运算）：
- 称量：`mass_g == target_g`
- 干物：`dry_u ≥ dry_min_g × 10000`
- 凝胶：`dry_u × gel_low_sag × 1000 ≤ gel_moment ≤ dry_u × gel_high_sag × 1000`
- 展示 SAG：`round_half_up(gel_moment / dry_u / 1000, 3)`

## 签发生命周期

- **门槛**：称量、干物、凝胶上下限四项全合格，且领用对账通过（`balanced` 且 `shortage_g == 0`），寻优状态为 `FEASIBLE`，缺一即返回 `CREDENTIAL_GATE_FAILED`（422）并列出阻断码，不出件。
- **重试幂等**：同一留档批号只出一份凭据（凭据号为凭据负载的 SHA-256），重试返回既有件（200），不重复出件。
- **撤回**：撤回后状态置 `REVOKED` 并记录 UTC 时间；状态仍可查询，但下载端点返回 410 停止下载；撤回后再点签发不会复活旧件、不产生新件。
- **留档复查**：撤回只改凭据登记处（`PECTIN_CREDENTIALS`），整份留档（`PECTIN_ARCHIVE`）原样保留，`GET /api/batches/<id>` 与留档页始终可复查。
- 未签发查询/下载返回 404；签发页逐批展示凭据状态，仅 `ISSUED` 提供下载入口。

## 陷阱登记

| TRAP | 原件现象 | 朴素错误 | 处理 | 位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 化验首列有 BOM | 批号列未识别 | 移除首 BOM | `app/modules/assay/reader.py` | `tests/test_assay.py::test_bom_and_split_header` |
| TRAP-04 | 化验接表 | 表头进清单 | 统计分段 | `app/modules/assay/reader.py` | `tests/test_assay.py::test_bom_and_split_header` |
| TRAP-05 | PJ-10 附多列 | 误读化验结果 | 逐行隔离 | `app/modules/assay/reader.py` | `tests/test_assay.py::test_extra_column_keeps_line` |
| TRAP-06 | PJ-01 全角千分位 | 原料重量读错 | NFKC 与格式校验 | `app/modules/assay/units.py` | `tests/test_assay.py::test_fullwidth_thousands_and_decimal_contract` |
| TRAP-07 | 哨兵和空格 | 当成零水分 | 稳定原因区分 | `app/reasons.py` | `tests/test_assay.py::test_blank_and_sentinel_are_distinct` |
| TRAP-10 | 按干物计算小数 | 浮点或提前取整 | 万分克整数累计 | `app/modules/dry/weights.py` | `tests/test_dry.py::test_mass_exact_with_fractional_moisture` |
| TRAP-14 | PJ-06 双化验冲突 | 后写覆盖 | 两个原件行均隔离 | `app/modules/assay/service.py` | `tests/test_assay.py::test_contradictory_assays_disable_both` |
| TRAP-15 | PJ-02 克和千克混写 | 重复入库 | 规范成克后判同批 | `app/modules/assay/units.py` | `tests/test_assay.py::test_kg_is_normalized_before_duplicate_detection` |
| TRAP-19 | PJ-02 与 PJ-04 均可配 | 随记录顺序 | 先批数再到期，再按批号 | `app/modules/blend/search.py` | `tests/test_blend.py::test_conflicting_valid_choices_resolve_by_expiry` |

## 对账规则

- 脏样本 16 条正文 = 7 采信 + 7 隔离 + 1 重复表头 + 1 空行。
- PJ-01 和 PJ-02 各取 5000 g。干物 4000+5000=9000 g，凝胶度 (4000×120+5000×180)/9000=153.333 SAG。
- 计划 10000 g = 领用 10000 g + 缺口 0 g。采信库存 27000 g = 领用 10000 g + 期末 17000 g。

试算库存源于输入快照。实际出库和电子签章由生产系统处理。本项目使用输入日期裁决有效期。
