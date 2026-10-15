# 算力智保 Demo 开发检查点

2026-10-15，任务01a13d66-27bd-77b3-a03b-d013d9e2d7df。

当前：用户询问能否根据现有信息完成开发，已开展本地独立Demo开发。原始两份Word与旧翼险智航工程保留。

本轮实现已完成，接口与分工见 docs/API_CONTRACT.md。根任务完整运行93项后端测试全部通过（有1条第三方弃用提示）；实际Uvicorn服务HTTP检查23项通过；Chrome浏览器15项检查通过；前端类型检查与构建通过。QA库单独位于 `/tmp/compute-insurance-qa-20261015/server.sqlite3`，未使用默认演示库。

四页：风险总览、资源调度、智能体助手、预案记录。已实现3企业、5供应商、5场景、13:00—17:00回放、预算/质量筛选、助手工具记录、SQLite持久化和三种格式导出。最终前端资产为index-DYIzsn9_.js与index-B_SJxqmo.css。截图及验收结果见docs/。

后续接手先读README和docs/TEST_RESULTS.md。本轮QA服务通过scripts/start.sh启动，交付前停止临时QA服务。用户使用“启动演示.command”或bash scripts/start.sh启动默认本地演示库；无需重写代码即可回放。

模型默认为offline；真实模型名称/密钥均未配置，无真实模型或企业/供应商验证。脚本和README已落盘，macOS启动入口为“启动演示.command”。
