# 接口

`POST /api/run`：JSON中的csv文本，省略使用样例；或multipart字段file。最大5MB。

`POST /api/m1`至`POST /api/m7`：独立运行到指定模块，JSON结构同运行接口。

`GET /api/history`：历史批次。`POST /api/review`接收id、revision和decision（通过或退回）。`GET /api/evidence.csv`提供单一证据导出。

结构错误422，版本变化409，文件过大413；错误返回code与message。所有页面可从左侧七个模块入口访问。

`GET /api/runs/<id>`读取指定批次；页面与证据CSV通过run_id查询参数绑定批次，模块导航保留该参数。

JSON请求体必须是对象，数组、标量、null、损坏JSON及错误上传字段返回400，且不运行默认样例。

## 复测管理

`POST /api/retest`：JSON中的csv文本（省略使用复测样例①）；或multipart字段file。可选limit限定本次处理条数，达到限量任务保持运行中。同内容重传复用任务：已完成直接复用，运行中自动续跑，均不新增版本。

`POST /api/retest/resume`：JSON含job_id与可选limit，从游标续跑中断任务；任务不存在返回404。

`GET /api/retest/jobs`：任务列表（版本、状态、进度）。

`GET /api/retest/view?batch=&view=current|signed&signoff=`：炉次视图。current为最新有效修订的当前结果；signed为签核时冻结的验收单，缺省取最新一张，可用signoff指定单号。视图参数非法422，炉次或验收单不存在404。

`POST /api/retest/signoff`：JSON含batch，把该炉次当前成分、混配、验收结论与修订集合冻结为验收单。成分未变重复签核复用原单；炉次无有效成分422。

`GET /api/retest/export.csv?batch=&view=current|signed&signoff=`：导出CSV。当前视图每行绑定实时修订集合摘要（current:哈希），签核视图绑定验收单号（signoff:单号）与冻结修订。

页面入口/retest，左侧导航08复测管理。
