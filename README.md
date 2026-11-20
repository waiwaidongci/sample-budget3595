# 榆灯触达样本预算台

内容触达基线点击率→最小可检测差异与预算→预注册方案；单双侧语义固定双侧，功效模拟固定seed。原生 HTML/CSS/JavaScript 多模块工作席，所有计算由 Python 完成。

## 模拟业务
榆灯研究协作组，12名分析师与业务人员，日常使用 `sample-budget-202611-1.csv` 手工抄表。当前三个痛点：观测与口径不可追溯、重算易出错、结果与复核割裂。上游提供独立合成业务观测；本应用接管数据登记、方法执行和输入冻结；下游负责人形成复测/预算方案，观察员获取复核后的CSV。

核心业务实体：CampaignPlan / BaselineScenario / PowerRun / BudgetDecision。源码 model/schema/service/controller/route 与前端 api/store/pages 完成链路，不依赖浏览器本地假数据。

## 功能与方法
- 触达计划、基线情景录入/编辑/删除；重名记录与非法数值明确拒绝。
- 两比例实验样本量正态近似与二项Monte Carlo功效验证。独立等样本双组、双侧正态近似。模拟功效用于检验近似；低事件率应谨慎采用，正式实验须另行预注册。
- 每次运行冻结参数、观测和SHA256。Redis任务由独立worker计算，写DB与共享产物卷；输入修改不会改写历史结果。
- 单城试投增量：没有随机对照的单城投放，用其他城市投放前逐日数据拟合对照权重，估算投放后点击率增量。见下节。
- 负责人复核不可覆盖；审计记录登录、数据改动、排队、复核与导出；240请求/分钟限流、全局可恢复错误。

## 单城试投增量
适用于“只在一个城市投放、没有随机对照”的试投，用其他城市作为对照估算增量。

1. **逐城每日录入**：试验城与对照城市都按城市+日期录入触达数、点击数。投放首日（含）之后算投放后。
2. **只接投放前**：封存前只接收投放前日报。封存与投放后数据并发提交时，投放后记录只有在封存成功后才会被接收（否则 409）。
3. **封存对照权重**：封存时只用投放前数据，在 `w>=0、Σw=1` 的单纯形上最小化逐日点击率残差（按试验城触达量加权），结果与投放前快照写入 `pilot_seals` 并带SHA256；之后不可重新拟合或改配。投放前完整覆盖不足2个对照城市则拒绝封存。
4. **迟到串投**：登记某对照城市的实际开始日后，该城自该日起的投放后数据全部失效。若实际开始日早于投放首日，按封存口径权重不重配，只给出提示，因为投放前数据可能已被污染。
5. **缺报或失效的区间**：某日对照城市缺报或串投失效时，这部分权重对应的点击率未知，按 0 到 1 端点计算对照基线与增量的上下界；原权重不重配、不转给其他城市。试验城自身缺报的日期不进入汇总，只列出。页面同时列出每日增量范围与受影响城市（原因、首末日期、天数、封存权重）。
6. **更正与并发**：封存后任何日报或串投变动都会推进计划版本。基于旧版本的运行（含已完成）标为 `superseded`，结果保留可查但不得作为当前结论；计算完成时若计划版本已前进，worker 同样只留档并标为 superseded。页面用“当前有效结论”标记唯一可信结果。

增量单位是百分点，区间是上下界而非置信区间：它只回答“在给定封存权重下，缺失那部分点击率取极端值时增量能落在哪里”。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18244 ，API http://localhost:19244/docs 。数据库映射 17744。无需Node构建。可以从中文和带空格目录启动。清理 `docker compose down -v --remove-orphans` 会删除本题演示数据卷。

|角色|账号|密码|权限与典型动作|
|---|---|---|---|
|admin 负责人|admin@demo.local|Research2026!|全部读写、批准复核、下载|
|analyst 分析师|analyst@demo.local|Research2026!|数据修改、创建任务、读取结果及下载；不能复核|
|viewer 观察员|viewer@demo.local|Research2026!|只读；仅可导出已复核结果|

## 一天的工作剧本
1. 09:00 admin登录，查“榆灯·冬季专题”。
2. 09:10 analyst核对 `sample-budget-202611-1.csv` 的seed记录。
3. 09:15 来源录入页检查 `基线点击率 (0–1)` 等业务字段，必要时编辑。
4. 09:20 分析执行页保留默认参数 `{"alpha": 0.05, "power": 0.8, "simulations": 10000}`，命名本轮研究。
5. 09:21 冻结输入并排队，worker实算，结果页自动刷新。
6. 09:25 阅读核心数值、方法边界、明细与SHA256；发现失败先修数据重跑。
7. 09:35 admin打开业务复核，写明限制与下一步动作，归档后不可覆盖。
8. 09:40 viewer读取复核意见并下载CSV，在操作留痕页核对下载事件。

seed是3个前瞻设计情景，每个计划1条基线/候选概率、成本和预算记录；本题用于实验前预算设计，不伪造实验后点击事件。预算与单位成本采用十进制除法向下取整，预计总成本四舍五入至分（ROUND_HALF_UP），避免0.6÷(0.1×2)浮点误差少算样本。预算每组触达上限200000；不足一次双组触达时预算可行样本数与功效均为0。

seed另建一个单城试投计划“榆灯·单城试投·冬季主城”：试验城“主城”、四座对照城市、投放首日 2026-12-01、14 天投放前日报。权重留给分析师在页面上封存，种子不代做这个人工决定；投放后日报也留空，需在封存后逐日录入。工作剧本的第 9 步：打开“单城试投”，封存权重，录入投放后日报，登记迟到串投，提交增量核算，在结果页阅读每日增量范围与受影响城市。

## 技术与目录
|部分|实现|
|---|---|
|前端|原生ES modules、HTML/CSS、Nginx1.27，无前端框架|
|API|Python3.11、FastAPI0.115、SQLAlchemy2、JWT、PBKDF2密码|
|计算|NumPy2.2、SciPy1.15，固定seed42|
|数据库|PostgreSQL16|
|任务|Redis7持久队列，Python独立worker，心跳healthcheck|

`frontend/src/`分api、stores、types、components/common、hooks、pages、router、utils、constants；`backend/src/`分config、models、schemas、services、controllers、routes、middlewares、utils、constants。单城试投链路对应 `models/pilot.py`、`schemas/pilot.py`、`services/pilot.py`、`services/pilot_algorithm.py`、`controllers/pilot.py`、`routes/pilot.py`，前端为 `pages/pilot.js`、`pages/pilot-result.js`、`stores/pilot.js`、`api/pilot.js`。`backend/scripts/seed_demo.py`自然键插入、重复不覆盖修改；`backend/migrations/README.md`说明schema版本。

环境变量 `.env.example`：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO。开发时在本地venv安装backend/requirements.txt，设置DATABASE_URL、REDIS_URL、JWT_SECRET再运行uvicorn；前端开发经Nginx代理 `/api/` 到不带前缀的API。

共享枚举：角色admin/analyst/viewer和队列queued/running/completed/failed（单城试投另有superseded“已被更正取代”）；后端`src/constants/enums.py`、认证与worker使用相同值；前端`src/types/enums.js`、状态与角色界面使用相同值。Google Fonts：Noto Serif SC + IBM Plex Mono；断网使用serif/monospace回退。

## 算法输入、失败态与复现
输入为选定批次全部观测和参数，输出核心数值、明细、解释；参数经后端严格白名单和范围验证。独立等样本双组、双侧正态近似。模拟功效用于检验近似；低事件率应谨慎采用，正式实验须另行预注册。。空批次拒绝；不完整字段/非有限数/非法计数拒绝；常量相关列与不足样本使任务failed并保留错误。固定seed42、输入checksum相同可复现。独立oracle：功效随样本趋势；公式对norm.ppf；MDE零与越界概率拒绝。

已知边界：小型本地研究应用，使用合成数据，不含企业SSO与外发邮件；结果由人工复核，不自动执行业务决策；单worker恢复queued/running任务，数据库与Redis间未采用分布式事务。以当前测试目录TESTING.md记录实际验证结果。

MIT License。
