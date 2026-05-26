# 发布文件清单

## 需要发布的文件和目录

### 核心目录
- `config/` - 配置文件目录
- `data/` - 数据库脚本目录
- `image/` - 图片资源目录
- `stock_analyzer/` - 股票分析器模块
- `strategy/` - 策略实现目录
- `trading/` - 交易相关代码目录
- `utils/` - 工具类目录
- `web/` - 前端文件目录

### 根目录文件
- `README.md` - 项目说明文件（含Logo和系统截图）
- `RELEASE_NOTES.md` - 版本发布说明
- `RELEASE_FILES.md` - 发布文件清单
- `LICENSE` - 许可证文件
- `CODE_OF_CONDUCT.md` - 行为准则
- `CONTRIBUTING.md` - 贡献指南
- `SECURITY.md` - 安全说明
- `requirements.txt` - 依赖文件
- `main.py` - 主脚本
- `web_server.py` - Web服务器脚本
- `start.bat` - 启动脚本

### 配置文件
- `config/config.yaml.template` - 配置模板
- `config/strategy_params.yaml` - 策略参数配置
- `config/strategy_order.yaml` - 策略排序配置
- `config/strategy_weights.json` - 策略权重配置
- `config/data_sources.json` - 数据源配置
- `config/database.yaml` - 数据库配置
- `config/risk_config.yaml` - 风险控制配置（新增）
- `config/strategy_kelly_config.yaml` - 凯利公式配置
- `config/strategy_name_mapping.yaml` - 策略名称映射
- `config/support_methods.yaml` - 支撑位计算方法
- `config/pool_removal_config.yaml` - 股票池移除配置

### 数据库脚本
- `data/DataSql.sql` - 数据库结构脚本

### 图片资源
- `image/imp.jpeg` - 系统界面截图

### 策略文件
- `strategy/*.py` - 所有策略实现文件（13个选股策略）

### 股票分析器文件
- `stock_analyzer/*.py` - 所有股票分析器模块
  - `stock_analyzer/data_fetcher.py` - 数据获取
  - `stock_analyzer/technical_analyzer.py` - 技术分析
  - `stock_analyzer/fundamental_analyzer.py` - 基本面分析
  - `stock_analyzer/sector_analyzer.py` - 行业分析
  - `stock_analyzer/fund_flow_analyzer.py` - 资金流分析
  - `stock_analyzer/event_analyzer.py` - 事件分析
  - `stock_analyzer/report_generator.py` - 报告生成

### 交易相关文件
- `trading/*.py` - 所有交易相关代码
  - `trading/backtest_engine.py` - 回测引擎
  - `trading/backtest_dao.py` - 回测数据访问
  - `trading/backtest_batch_queue.py` - 批量回测队列
  - `trading/khunter_api.py` - 狩猎场API
  - `trading/khunter_dao.py` - 狩猎场数据访问
  - `trading/stock_score_api.py` - 股票评分API
  - `trading/stock_score_calculator.py` - 股票评分计算
  - `trading/strategy_runner.py` - 策略运行器（新增）
  - `trading/macd_bollinger_strategy.py` - 顺势宝策略（新增）

### 工具类文件
- `utils/*.py` - 所有工具类文件
  - `utils/log_config.py` - 日志配置与自动清理
  - `utils/risk_manager.py` - 风险管理（新增）
  - `utils/risk_controller.py` - 风险控制器（新增）
  - `utils/var_calculator.py` - VaR计算器（新增）
  - `utils/risk_config_loader.py` - 风险配置加载器（新增）
  - `utils/akshare_fetcher.py` - AKShare数据获取
  - `utils/data_collection_service.py` - 数据采集服务
  - `utils/feature_config_checker.py` - 配置文件检测

### 前端文件

#### 模板文件
- `web/templates/index.html` - 主页面模板

#### 静态资源 - CSS
- `web/static/css/style.css` - 主样式表
- `web/static/css/khunter.css` - KHunter特定样式

#### 静态资源 - JavaScript (根级)
- `web/static/js/app.js` - 应用主入口
- `web/static/js/kline_chart.js` - K线图表功能
- `web/static/js/data_update.js` - 数据更新功能
- `web/static/js/data_update_simple.js` - 简化数据更新
- `web/static/js/init_simple.js` - 简化初始化
- `web/static/js/selection_history.js` - 选股历史
- `web/static/js/trading.js` - 交易功能
- `web/static/js/error_handler.js` - 错误处理
- `web/static/js/retry_policy.js` - 重试策略
- `web/static/js/dashboard_stats.js` - 看板统计（新增）

#### 静态资源 - JavaScript 模块 (modules/)
- `web/static/js/modules/navigation.js` - 页面导航
- `web/static/js/modules/stocks.js` - 股票相关功能
- `web/static/js/modules/selection.js` - 选股功能
- `web/static/js/modules/analysis.js` - 分析功能
- `web/static/js/modules/strategies.js` - 策略配置
- `web/static/js/modules/history.js` - 历史记录
- `web/static/js/modules/ranking.js` - 排名功能
- `web/static/js/modules/utils.js` - 工具函数
- `web/static/js/modules/websocket.js` - WebSocket连接
- `web/static/js/modules/khunter.js` - KHunter狩猎功能
- `web/static/js/modules/backtest.js` - 回测功能
- `web/static/js/modules/backtest-batch.js` - 批量回测
- `web/static/js/modules/backtest-executor.js` - 回测执行器
- `web/static/js/modules/backtest-api.js` - 回测API
- `web/static/js/modules/backtest-error-handler.js` - 回测错误处理
- `web/static/js/modules/backtest-performance.js` - 回测性能
- `web/static/js/modules/backtest-utils.js` - 回测工具
- `web/static/js/modules/backtest-ux.js` - 回测用户体验
- `web/static/js/modules/execution-plan.js` - 执行计划
- `web/static/js/modules/market_temperature.js` - 市场温度
- `web/static/js/modules/money_flow.js` - 资金流向
- `web/static/js/modules/risk.js` - 风险控制（新增）
- `web/static/js/modules/strategy-runner.js` - 策略运行器（新增）

#### 静态资源 - 图片
- `web/static/images/logo.svg` - 系统Logo
- `web/static/images/favicon.svg` - 网站图标
- `web/static/images/logo-preview.html` - Logo预览页面

## 不需要发布的文件

### 临时文件和目录
- `logs/` - 日志目录（运行时自动创建）
- `__pycache__/` - Python缓存目录
- `*.pyc` - 编译后的Python文件
- `.coverage` - 测试覆盖率文件

### 数据库文件
- `stock_selection.db` - 本地数据库文件（运行时自动创建）

### 测试文件
- `test/` - 测试目录
- `test_*.py` - 测试脚本

### IDE配置文件
- `.kiro/` - Kiro IDE配置
- `.vscode/` - VS Code配置
- `.git/` - Git版本控制目录

### 其他临时文件
- `*.log` - 日志文件
- `*.bak` - 备份文件
- `*.swp` - Vim交换文件
- `*.tmp` - 临时文件
- `*.zip` - 压缩包文件
- `sync_files.py` - 临时同步脚本
- `cleanup_khunter.py` - 临时清理脚本

## 发布检查清单

### 前端功能验证
- [x] 页面导航菜单正常工作
- [x] 所有JavaScript模块正确加载
- [x] CSS样式表完整
- [x] 图片资源完整（Logo、Favicon、系统截图）
- [x] 数据加载显示正确（暂无数据vs加载中）
- [x] 所有API端点可访问
- [x] 策略运行器菜单显示正常（有配置文件时）

### 后端功能验证
- [x] 数据库初始化脚本完整
- [x] 所有Python依赖已列出
- [x] 配置文件模板正确
- [x] 策略实现完整（13个选股策略）
- [x] 择时策略完整（5个）
- [x] 风险控制模块完整
- [x] 策略运行器功能正常

### 文档完整性
- [x] README.md包含完整说明（含Logo、系统截图、五维度评分体系详解）
- [x] RELEASE_NOTES.md版本信息更新
- [x] RELEASE_FILES.md发布清单完整
- [x] 所有策略说明书已包含（12个）
- [x] 安装和使用指南清晰

## 发布版本信息

**发布日期**: 2026-05-26
**版本**: 1.4.0
**状态**: 生产就绪

### 版本更新内容

#### 新增策略
- **选股策略**：趋势起点策略、2560战法
- **择时策略**：顺势宝策略（MACD金叉 + 布林带上穿中轨）

#### 新增功能模块
- **策略运行器**：自动化策略执行，支持配置检测
- **风险控制模块**：VaR风险评估、风险控制器
- **日志管理**：自动清理10天前日志

#### 新增文件
- `strategy/trend_start_strategy.py` - 趋势起点策略
- `strategy/strategy_2560_selection.py` - 2560战法
- `trading/strategy_runner.py` - 策略运行器
- `trading/macd_bollinger_strategy.py` - 顺势宝策略
- `utils/risk_manager.py` - 风险管理
- `utils/risk_controller.py` - 风险控制器
- `utils/var_calculator.py` - VaR计算器
- `utils/risk_config_loader.py` - 风险配置加载器
- `config/risk_config.yaml` - 风险配置文件
- `image/imp.jpeg` - 系统界面截图

#### 文档更新
- README.md：添加Logo和系统截图，更新策略列表
- RELEASE_NOTES.md：更新版本信息和新增功能说明
- RELEASE_FILES.md：更新发布清单