# 算力智保 Demo

算力短缺预警与应急资源匹配的本地研究演示系统，包含风险总览、资源调度、智能体助手与预案记录四页。使用仓库内置的模拟企业、供应商和场景即可独立运行。

企业与供应商数据均为模拟数据。缺口测算、资源筛选、费用计算、记录保存和导出实际运行。人工确认仅生成模拟记录。保险服务范围、双指数触发与给付规则保留待确认状态。

## 启动

macOS双击本目录的 `启动演示.command`，浏览器会自动打开。终端窗口保留运行日志，按Ctrl+C停止。首次安装需要联网下载开发依赖，后续离线模式无需联网。

命令行也可启动：

```bash
git clone https://github.com/WXR060318/compute-insurance-agent-demo.git
cd compute-insurance-agent-demo
bash scripts/setup.sh
bash scripts/build.sh
bash scripts/start.sh
```

默认地址 `http://127.0.0.1:8765`。端口冲突时用 `DEMO_PORT=8766 bash scripts/start.sh`。启动脚本不会终止其他工程进程。

环境需要Node.js、npm和Python3.11或更高版本。当前本机使用Python3.12与Node23。

已有源码目录时，进入该目录后从 `bash scripts/setup.sh` 开始。安装脚本会创建本机 `.env`；仓库仅提供 `.env.example`。依赖、构建结果和运行数据库在本机生成。

## 如何演示

先选择“星河模型”“需求激增”，将回放时间设为13:30。预期结果为当前容量8张、计划高峰需求12张、预计缺口4张，14:00—16:00需要补充8卡时。默认推荐供应商A，模拟采购成本96元。

切换供应商排序、预算和质量门槛，查看筛选与排除理由。向助手追问“为什么不选更便宜的B？”或“预算只有80元”，观察结果变化。生成处置预案后可以保存人工模拟确认，并导出HTML、JSON或CSV。

另外提供平稳运行、供给下降、供应不足、数据失效场景。回放范围13:00—17:00，可以观察需求高峰结束后的恢复。

完整演示节奏见 `docs/DEMO_SCRIPT.md`。四个页面的具体名称以当前界面为准。

## 接入模型

默认 `.env` 中 `AI_MODE=offline`，使用明确标注的离线规则助手，不发送模型请求。可以通过本项目的 `.env` 配置真实模型：

```dotenv
AI_MODE=live
DEEPSEEK_API_KEY=在本机填写
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=填写账号实际可用的模型标识
```

修改配置后重启服务。密钥只在后端使用，不进入前端包或导出记录。模型调用失败时显示故障回退及原因；离线助手仍可展示核心业务。真实模型配置与连通情况以 `docs/TEST_RESULTS.md` 的实际记录为准。

模型通过受限的工具接口读取快照、测算缺口、匹配资源、查询服务草案和生成预案。最终资源与金额以服务端计算结果为准。

## 开发与验证

```bash
bash scripts/test.sh
```

后端测试使用临时数据库与离线/模拟模型响应。工程验证与真实业务有效性分开记录，见 `docs/TEST_RESULTS.md`。本演示未验证真实企业接口、供应商库存与履约能力，也不提供真实保险责任或给付结论。

2026年10月15日交付验证：93项后端测试、23项真实HTTP检查、15项Chrome浏览器流程检查通过；TypeScript检查与生产构建通过。已检查1440px桌面和390px手机布局。

本机已启动服务时，可再次运行以下验收；它们会在所连接服务的数据库中生成模拟预案，建议对独立QA数据库执行：

```bash
.venv/bin/python scripts/smoke_api.py
node scripts/browser_qa.mjs
```

浏览器验收使用本机Google Chrome，截图保存在 `docs/screenshots/`，结构化结果保存在 `docs/browser-qa-results.json`。

```text
backend/app/     FastAPI、演示数据、规则引擎、SQLite、模型工具适配
backend/tests/   规则、持久化、API与模型适配测试
frontend/       React和TypeScript四页交互界面
scripts/        安装、构建、启动、测试
runtime/        本机演示数据库
docs/           接口约定、演示脚本、验证记录
CHECKPOINT.md   当前实现状态与续接入口
```

不删除数据库即可保留历史预案。需要从空数据开始时，先停止服务，备份 `runtime/`，再单独指定新的 `DEMO_DB_PATH` 启动。原始Word、已有构建方案和“翼险智航”工程均独立保留。
