Schema v1 is defined by the SQLAlchemy models and created at startup via Base.metadata.create_all. For this local small application no destructive migration is run. Back up named db-data before modifying schemas.

Schema v2 adds the single-city pilot tables, created automatically by the same `create_all`:

- `pilot_plans` — 试投计划、试验城、投放首日、当前 `revision`、`sealed_at`。
- `pilot_daily` — 逐城每日触达/点击，唯一键 `(plan_id, city, date)`。
- `pilot_seals` — 每个计划一份封存件，含权重、拟合指标、投放前快照与 SHA256；唯一键 `plan_id`。
- `pilot_spillovers` — 迟到串投，唯一键 `(plan_id, city, actual_start_date)`。
- `pilot_runs` — 增量核算快照与结果，`input_revision` 记录冻结时的计划版本；`status` 可为 queued/running/completed/failed/superseded。

`create_all` 只新增缺失表，不会改动既有表。已有部署升级后首次启动会直接建出这五张空表，不影响 `studies`/`observations`/`runs`/`reviews`/`audits`。若需回退，先备份 `db-data` 卷，再手工删除 `pilot_*` 表。
