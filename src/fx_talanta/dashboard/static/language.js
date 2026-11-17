// UI labels only: never translate stored evidence, field values, identifiers or JSON.
const labels = {
  "Export agent research report": "导出智能体研究报告",
  "Agent-selected research period": "智能体选择的研究期间",
  "Why this period?": "为什么选择这个期间？",
  "Review the rules, then let the agent plan and run the research.":
    "审阅规则后，让智能体规划并执行研究。",
  "Agent-led strategy validation": "智能体主导策略验证",
  "Preview agent plan": "预览研究计划",
  "Run agent research": "启动智能体研究",
  "Review rules and start agent research": "审阅规则并启动研究",
  "Advanced: choose datasets and run individual studies":
    "高级：手动选择数据及运行研究",
  "Validate your strategy": "验证策略",

  "Tested symbol": "测试货币对",
  "Why no closed trades?": "为什么没有已平仓交易？",
  "Continue current strategy": "继续当前策略",
  Overview: "概览",
  Strategies: "策略",
  "Market & Data": "市场与数据",
  Activity: "活动记录",
  Describe: "描述",
  Review: "审阅",
  Backtest: "回测",
  Results: "结果",
  "Create a strategy": "创建策略",
  "Review your strategy": "审阅策略",
  "Backtest your strategy": "回测策略",
  "Review backtest results": "查看回测结果",
  "Continue to backtest": "继续回测",
  "Run backtest": "运行回测",
  "Saved strategies": "已保存的策略",
  "Write a strategy manually": "手动编写策略",
  "Revise this strategy": "修订此策略",
  "Describe your strategy": "描述策略",
  "Review rules and risk limits": "审阅规则与风险限制",
  "Choose data and run a backtest": "选择数据并运行回测",
  "Advanced: registered studies": "高级：已注册研究",
  "Dataset windows and cost assumptions": "数据时间窗口与成本假设",

  "Skip to workspace": "跳转到工作区",
  "OPERATING WORKSPACE": "操作工作区",
  OBSERVATORY: "市场观察",
  Workspace: "工作区",
  Observatory: "市场观察",
  "Trading disabled": "交易已禁用",
  "◈ Overview": "◈ 概览",
  "Strategies & research": "策略与研究",
  "≋ Data channels": "≋ 数据通道",
  "▤ Evidence journal": "▤ 证据日志",
  "! Incidents": "! 事件",
  "▦ Calendar & news": "▦ 日历与新闻",
  "◇ Advisor": "◇ 顾问",
  "READ-ONLY WORKSPACE": "只读工作区",
  "No order controls.": "无下单控制。",
  "No broker connections.": "未连接经纪商。",
  "M5 / Inspection surface": "M5 / 检查界面",
  "SEE THE EVIDENCE. UNDERSTAND THE DECISION.": "查看证据，理解决策。",
  "Market observatory": "市场观察",
  "A clear view of inputs, decisions and the reasons to wait.":
    "清晰查看输入、决策及等待原因。",
  "Refresh snapshot": "刷新快照",
  "Export inspection report": "导出检查报告",
  "Strategy & research workspace": "策略与研究工作区",
  "New candidate": "新建候选策略",
  Name: "名称",
  Hypothesis: "策略假设",
  "Inputs, sessions and calendar/news policy": "输入、交易时段及日历/新闻规则",
  "Entry signals and HOLD conditions": "入场信号与观望条件",
  "Exit and protection rules": "退出与保护规则",
  "Portfolio and combined USD exposure policy": "投资组合及合计美元敞口规则",
  "Evaluation plan: costs, windows, benchmarks and rejection criteria":
    "评估计划：成本、窗口、基准及拒绝标准",
  "Proposed risk per trade (%)": "拟议单笔风险 (%)",
  "Proposed total open risk (%)": "拟议总持仓风险 (%)",
  "Proposed daily loss limit (%)": "拟议每日亏损上限 (%)",
  "Declared authorship": "声明作者",
  "User draft": "用户草稿",
  "Imported AI proposal (unverified)": "导入的 AI 提案（未验证）",
  "Provenance: author or model, prompt and evidence references":
    "来源：作者或模型、提示词及证据引用",
  "Save new revision": "保存新版本",
  "Freeze saved revision": "冻结已保存版本",
  "Export selected revision": "导出选中版本",
  "Saved versions": "已保存版本",
  "Research readiness": "研究就绪状态",
  "AI proposals and historical research": "AI 提案与历史研究",
  "Research brief": "研究要求",
  "Generate AI proposal": "生成 AI 提案",
  "Reviewed executable rules (JSON)": "已审核的可执行规则 (JSON)",
  "Historical research bundle (dataset + experiment + acceptance criteria)":
    "历史研究文件（数据集 + 实验 + 验收标准）",
  "I reviewed these executable rules against the selected frozen candidate; any differences are explicit research assumptions.":
    "我已对照选中的冻结策略审核这些可执行规则；任何差异均为明确的研究假设。",
  "Register selected frozen candidate": "注册选中的冻结策略",
  "Registered experiment": "已注册实验",
  Window: "窗口",
  training: "训练",
  validation: "验证",
  holdout: "留出测试",
  "Run registered backtest": "运行已注册回测",
  "Refresh research evidence": "刷新研究证据",
  "Review proposal in form": "在表单中审核提案",
  "Translate input (preview only)": "翻译输入（仅预览）",
  "English and Chinese inputs are accepted directly. Translation uses the AI provider; nothing is saved or applied automatically. Provider retention policies may apply.":
    "可直接输入中文或英文。翻译使用 AI 服务，不会自动保存或应用。服务商的数据保留政策可能适用。",
  "Text to translate": "待翻译文本",
  "Target language": "目标语言",
  Translate: "翻译",
  "Clear translation": "清空翻译",
  "Translation preview": "翻译预览",
  "Recorded inputs · never live": "记录的输入 · 非实时",
  "EXECUTION AUTHORITY": "执行权限",
  Disabled: "已禁用",
  "No gateway attached": "未连接网关",
  "ENTRY QUOTE CEILING": "入场报价时效上限",
  "Original timestamp + clock bound": "原始时间戳 + 时钟误差范围",
  "BROKER POSITIONS": "经纪商持仓",
  Unknown: "未知",
  "No current reconciliation": "尚无当前对账",
  "STRATEGY PROMOTION": "策略晋级",
  "Not qualified": "未通过资格验证",
  "B01 · rejected for promotion": "B01 · 晋级被拒绝",
  "Data channels": "数据通道",
  "Evidence journal": "证据日志",
  "Calendar & news": "日历与新闻",
  "Coverage unqualified": "覆盖范围未验证",
  "BLS calendar": "BLS 日历",
  "Import a BLS .ics file": "导入 BLS .ics 文件",
  "Save to inspection journal": "保存到检查日志",
  "Matched comparison": "配对比较",
  "Registered study receipts": "已注册研究回执",
  "Not configured": "未配置",
  "Incidents & state transitions": "事件与状态转换",
  "Search retained incidents": "搜索已保留事件",
  "Search incidents": "搜索事件",
  Advisor: "顾问",
  "Ask advisor": "询问顾问",
  Send: "发送",
  Question: "问题",
  "Evidence trail": "证据链",
  "Recorded broker observation": "已记录的经纪商观察",
  "Refresh local notifications": "刷新本地通知",
  "Simulator administration": "模拟器管理",
  "Inspect simulator": "检查模拟器",
  Action: "操作",
  "Owned position": "所属持仓",
  None: "无",
  "Preview simulator action": "预览模拟器操作",
  "Confirm preview": "确认预览",
  "Revoke this operator session": "撤销本次操作员会话",
  "Validate and retain study": "验证并保留研究",
  "Import matched-offline-study/1 JSON": "导入 matched-offline-study/1 JSON",
  "Sign in": "登录",
  "Sign out": "退出登录",
  "Sign out all sessions": "退出所有会话",
  Password: "密码",
  "Repeat password": "重复密码",
  "Create account": "创建账户",
  "Set up your workspace": "设置工作区",
};
Object.assign(labels, {
  "Trading lifecycle": "交易生命周期",
  "EUR/USD and USD/JPY · Offline research · No active trading strategy":
    "EUR/USD 和 USD/JPY · 离线研究 · 无活跃交易策略",
  "Latest 100 revisions. Select a version to inspect its exact specification.":
    "最近 100 个版本。选择版本以检查其精确规格。",
  "Not evaluated. Freezing does not qualify a strategy.":
    "尚未评估。冻结不代表策略通过资格验证。",
  "Reviewed executable mapping: required for each registration":
    "每次注册均需审核可执行规则映射",
  "Candidate-bound historical dataset: upload and register below":
    "与候选策略绑定的历史数据集：在下方上传并注册",
  "Frozen cost profile and development/holdout windows: not registered":
    "冻结成本配置及开发/留出窗口：尚未注册",
  "Backtest results below; promotion remains unavailable":
    "回测结果见下方；晋级仍不可用",
  "INPUT OBSERVABILITY": "输入可观测性",
  "Channel health & quote timing": "通道健康与报价时效",
  "Fresh ≤ 2s including clock uncertainty": "新鲜度 ≤ 2 秒（含时钟不确定性）",
  "Observer ceiling: 5s": "观察器上限：5 秒",
  "Fresh ≠ permission to enter": "新鲜报价 ≠ 允许入场",
  "Service and local notifications": "服务与本地通知",
  "Operator capability": "操作员权限",
  "Type SIMULATOR ONLY to confirm": "输入 SIMULATOR ONLY 以确认",
  "SEPARATE READ-ONLY JOURNAL": "独立只读日志",
  "HISTORICAL OPERATING SUMMARY": "历史运行摘要",
  "Outcomes & model usage": "结果与模型用量",
  "DECISIONS & RISK": "决策与风险",
  Show: "显示",
  "All evidence": "全部证据",
  Decisions: "决策",
  "Risk checks": "风险检查",
  Execution: "执行",
  Experience: "经验",
  Lessons: "教训",
  "Search evidence": "搜索证据",
  "No matching records in this snapshot.": "此快照中无匹配记录。",
  "RECORDED LINKS": "已记录的关联",
  "EVENT READINESS": "事件就绪状态",
  "OFFLINE EXPERIMENTS": "离线实验",
  "LOCAL INSPECTION HISTORY": "本地检查历史",
  "Show new incident changes in this page": "在此页面显示新事件变化",
  "Older matching incidents": "更早的匹配事件",
  "Latest incidents": "最新事件",
  "SAFETY BOUNDARY": "安全边界",
  "Why trading stays blocked": "交易为何保持阻止状态",
  "M5 qualification gates": "M5 资格门槛",
  "EVIDENCE, NOT ASSUMPTIONS": "基于证据，而非假设",
  "Record in focus": "当前关注记录",
  "Workspace questions": "工作区问题",
  "Why are we waiting?": "为何仍在等待？",
  "Explain quote latency": "解释报价延迟",
  "Welcome to your evidence workspace.": "欢迎使用证据工作区。",
  "Use bounded model evidence selection": "使用受限模型证据选择",
  "Check same explanation request": "检查同一解释请求",
  "Ask about this workspace": "询问此工作区",
  "Answer language": "回答语言",
  "No order, pause, resume or policy command is exposed.":
    "未提供下单、暂停、恢复或策略指令。",
  "Evidence first. Authority bounded.": "证据优先，权限受限。",
  Username: "用户名",
});
Object.assign(labels, {
  "1. Describe your research and generate a proposal":
    "1. 描述研究要求并生成提案",
  "2. Review, save and freeze your candidate": "2. 审核、保存并冻结候选策略",
  "3. Register historical inputs and run a backtest":
    "3. 注册历史输入并运行回测",
  "Start a manual candidate": "手动创建候选策略",
  "Optional: translate your input": "可选：翻译输入",
  "No candidate fields are required to generate a proposal. Describe your goals and constraints in English or Chinese.":
    "生成提案不需要填写候选策略字段。请用中文或英文描述目标和约束。",
  "Start with a research brief, review an AI proposal, then save and freeze a candidate before backtesting. Nothing here authorizes trading.":
    "先描述研究要求并审核 AI 提案，再保存和冻结候选策略，然后回测。此流程不授予交易权限。",
  "Choose Review proposal in form above to populate these fields. Edit and save your candidate, then freeze the version you want to backtest. Or start manually without AI.":
    "点击上方“在表单中审核提案”填入字段。编辑并保存候选策略，然后冻结要回测的版本。也可不使用 AI，直接手动创建。",
});
Object.assign(labels, {
  "Historical dataset": "历史数据集",
  "Select an available dataset": "选择可用数据集",
  "Advanced: import a research bundle": "高级：导入研究文件",
  "Use an uploaded bundle instead of the selected dataset":
    "使用上传文件而非选中的数据集",
  "Windows and cost assumptions are fixed for each dataset. Registration caps risk at the lower of the dataset policy and your frozen candidate limits.":
    "每个数据集的窗口及成本假设固定。注册时风险上限取数据集规则与冻结候选策略限制中的较低值。",
});
Object.assign(labels, {
  "Saved AI proposal rules": "已保存的 AI 提案规则",
  "Select a saved proposal": "选择已保存的提案",
  "Load proposal rules for review": "加载提案规则以供审核",
  "Loading rules keeps your selected candidate unchanged. Review the mapping again before registering.":
    "加载规则不会更改选中的候选策略。注册前请重新审核规则映射。",
});
Object.assign(labels, {
  "No frozen candidate selected. Choose one in Step 2.":
    "尚未选择冻结候选策略。请在第 2 步选择。",
});
Object.assign(labels, {
  "Frozen candidate for this backtest": "本次回测的冻结候选策略",
  "Select a frozen candidate": "选择冻结候选策略",
});
const languageSelect = document.getElementById("ui-language");
let currentLanguage = "en";
const originals = new Map();
const normalizeLabel = (text) => text.replace(/\s+/g, " ").trim();
// Preserve implicit option values before translating their display labels.
document.querySelectorAll("option:not([value])").forEach((o) => {
  o.value = o.textContent;
});
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
while (walker.nextNode()) {
  const node = walker.currentNode;
  if (
    !node.parentElement.closest("textarea,script,style,pre,code") &&
    labels[normalizeLabel(node.data)]
  )
    originals.set(node, node.data);
}
function applyLanguage() {
  document.documentElement.lang = currentLanguage === "zh" ? "zh-CN" : "en";
  for (const [node, original] of originals) {
    const translated = labels[normalizeLabel(original)];
    // Do not overwrite a dynamic evidence value replacing an initial label.
    if (node.data !== original && node.data !== translated) continue;
    node.data = currentLanguage === "zh" ? translated : original;
  }
}
languageSelect.querySelectorAll("button").forEach((button) => {
  button.addEventListener("click", () => {
    currentLanguage = button.dataset.language;
    languageSelect
      .querySelectorAll("button")
      .forEach((item) =>
        item.setAttribute("aria-pressed", String(item === button)),
      );
    applyLanguage();
  });
});
const input = document.getElementById("translation-input");
const output = document.getElementById("translation-output");
const status = document.getElementById("translation-status");
let translationEpoch = 0;
function clearTranslation() {
  translationEpoch++;
  input.value = "";
  output.value = "";
  status.textContent = "";
}
document
  .getElementById("translation-clear")
  .addEventListener("click", clearTranslation);
window.addEventListener("pagehide", clearTranslation);
window.addEventListener("pageshow", clearTranslation);
document
  .getElementById("translate-input")
  .addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const epoch = ++translationEpoch;
    const zh = currentLanguage === "zh";
    if (!input.value.trim()) {
      status.textContent = zh
        ? "请输入待翻译文本。"
        : "Enter text to translate.";
      return;
    }
    button.disabled = true;
    output.value = "";
    status.textContent = zh ? "正在翻译…" : "Translating…";
    try {
      const result = await api("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: input.value,
          target: document.getElementById("translation-target").value,
        }),
      });
      if (epoch !== translationEpoch) return;
      output.value = result.text;
      status.textContent = zh
        ? "仅预览，未保存。请核对数字和规则。"
        : "Preview only; not saved. Review numbers and rules.";
    } catch (_) {
      if (epoch === translationEpoch)
        status.textContent = zh
          ? "翻译不可用，未修改任何输入。"
          : "Translation unavailable; no input changed.";
    } finally {
      button.disabled = false;
    }
  });

// Newly rendered action labels may arrive after loading research evidence.
const actionObserver = new MutationObserver((records) => {
  for (const record of records)
    for (const added of record.addedNodes) {
      if (added.nodeType !== Node.ELEMENT_NODE) continue;
      const buttons = added.matches("button")
        ? [added]
        : added.querySelectorAll("button");
      for (const button of buttons)
        for (const node of button.childNodes) {
          if (
            node.nodeType === Node.TEXT_NODE &&
            labels[normalizeLabel(node.data)]
          )
            originals.set(node, node.data);
        }
    }
  applyLanguage();
});
actionObserver.observe(document.body, { childList: true, subtree: true });

window.addEventListener("fx-page-change", () => {
  for (const el of document.querySelectorAll(".heading h1, #page-breadcrumb")) {
    for (const child of el.childNodes)
      if (
        child.nodeType === Node.TEXT_NODE &&
        labels[normalizeLabel(child.data)]
      )
        originals.set(child, child.data);
  }
  applyLanguage();
});
