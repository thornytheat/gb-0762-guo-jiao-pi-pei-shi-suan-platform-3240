# 果胶批配试算台

原料工程师可检查化验单、核算干物、验现有配方、按离散称量寻优并留档。首页展示配方余量轨。顶部横向工序和左侧导航可直达各环节。来料争议样本包含互相矛盾的化验记录与不可试配的原提案。

`docker compose up --build` 后访问 `http://localhost:18461/`。本地安装 `pip install -r requirements.txt` 后，执行 `python -m flask --app app.main run --port=18461`，使用 `pytest -q` 验收。`PECTIN_ARCHIVE` 是留档目录，`PECTIN_CREDENTIALS` 是凭据登记目录，Compose 将二者保存在命名卷中。

预览和留档 API 接收 `{"sample":"dirty"}`、`{"sample":"clean"}` 或 `{ "assays":"CSV", "plan":{...}, "proposal":{"批号":2500} }`。计划示例见 `sample_data/dirty/trial.json`。从留档页提交，再到试配签发页审读和下载凭据。

## 凭据签发（最小披露）

客户凭据**不附整份留档**，只含计划约束与聚合结果（总湿重、总干物整数、总凝胶矩、SAG 展示值、对账结论、门槛判定、源摘要），不含批号、逐批化验、逐批库存与寻优分配；客户凭整数叉乘即可独立复算凝胶上下限，详见 [模块与复算](docs/DEPTH.md)。

- 签发：`POST /api/credentials/<batch_id>`，称量/干物/凝胶全合格且领用对账通过才出件；重试返回同一凭据，不重复出件。
- 状态：`GET /api/credentials/<batch_id>`（含已撤回），列表 `GET /api/credentials`。
- 撤回：`POST /api/credentials/<batch_id>/revoke`，旧凭据立即失效；下载 `GET /api/download/<batch_id>` 对撤回件返回 410、未签发返回 404。
- 留档原件不受撤回影响：`GET /api/batches/<batch_id>` 始终可复查。

- [模块与复算](docs/DEPTH.md)
- [数据定义](docs/DATA-DICTIONARY.md)
