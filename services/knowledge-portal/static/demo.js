const scenarios = {
  panorama: {
    command: "帮我出具这家企业全景分析报告",
    progress: ["正在建立企业主体锚点", "正在核对业务、知识产权与风险", "正在形成双版本事实底稿"],
    title: "具备进一步合作评估价值",
    summary: "公开信息显示业务方向较稳定，但重大项目申报前仍需补充内部经营与研发数据。",
    metrics: [
      ["主体可信度", "较高", "工商主体与公开业务一致"],
      ["发展信号", "3 类", "产品、研发、市场均有记录"],
      ["待核验", "4 项", "财务、客户、产能与研发"]
    ],
    action: "取得近三年审计报告、知识产权清单和主导产品收入明细后，再进入项目匹配。",
    deadline: "发现开放项目时自动显示剩余天数"
  },
  roadmap: {
    command: "请规划示例企业未来三年的项目成长路径",
    progress: ["正在识别企业发展阶段", "正在并行检索政策与名单", "正在生成近期、培育和跃迁路线"],
    title: "建议采用“基础夯实—能力跃迁—标杆申报”路线",
    summary: "先完成基础资质和研发管理闭环，再进入高等级项目，避免为了赶批次牺牲证据质量。",
    metrics: [
      ["近期申报", "2 项", "满足基础门槛后优先推进"],
      ["培育方向", "4 项", "需要持续补齐研发与市场证据"],
      ["观察项目", "3 项", "等待企业规模或政策窗口成熟"]
    ],
    action: "先锁定企业所在城市、主导产品边界和未来投资计划，再核验每个项目当期通知。",
    deadline: "示例开放项目 · 距企业截止 12 天"
  },
  checkup: {
    command: "帮我体检这份专精特新申报材料",
    progress: ["正在识别申请书版本", "正在复算指标并核对专利状态", "正在执行跨章节一致性门禁"],
    title: "材料框架完整，但存在三类高影响问题",
    summary: "主导产品边界、收入归集和知识产权映射尚未闭环，建议先修底稿再改正文。",
    metrics: [
      ["可保留", "8 项", "事实和叙事已基本闭合"],
      ["需替换", "3 项", "表述与产品边界不一致"],
      ["补证后保留", "5 项", "缺少测算过程或内部依据"]
    ],
    action: "先统一主导产品名称和收入边界，再联动修改产业链、市场占有率、专利与企业简介。",
    deadline: "材料体检不自动提交或发送"
  },
  patent: {
    command: "根据现有资料规划示例企业的十个专利方向",
    progress: ["正在拆解产品技术模块", "正在建立检索与现有技术计划", "正在形成分层专利主题"],
    title: "形成结构、工艺、控制与应用四层布局",
    summary: "方向覆盖核心部件、关键工艺、控制策略与场景应用，正式申请前仍需完成查新和交底。",
    metrics: [
      ["核心专利", "3 组", "围绕关键结构与作用机理"],
      ["外围专利", "4 组", "围绕工艺、控制和检测"],
      ["防御专利", "3 组", "围绕替代结构与应用场景"]
    ],
    action: "优先完成技术特征表和专利检索，再决定发明、实用新型及申请节奏。",
    deadline: "审中专利不会被标记为授权成果"
  },
  tax: {
    command: "帮我出具示例制造企业金税四期分析报告",
    progress: ["正在复算三张财务报表", "正在筛查税务与往来风险", "正在形成风险等级与整改顺序"],
    title: "发现两项优先核验风险与三项管理改进",
    summary: "示例结果仅展示分析结构；真实业务必须使用企业提供的可靠财务、税务和合同资料。",
    metrics: [
      ["高关注", "2 项", "需核对收入确认和往来穿透"],
      ["管理改进", "3 项", "研发、存货和发票留痕"],
      ["数据缺口", "4 类", "税表、合同、明细账和凭证"]
    ],
    action: "补齐税务申报表、主要销售合同和往来明细后，再形成正式风险结论。",
    deadline: "无可靠数据时不推算企业财务"
  }
};

const buttons = [...document.querySelectorAll(".scenario-button")];
const output = document.querySelector("#scenario-output");
const progressBar = document.querySelector("#progress-bar");
const progressLabel = document.querySelector("#progress-label");
const runButton = document.querySelector("#run-demo");
let activeScenario = "panorama";
let progressTimer;

function setText(id, value) {
  const element = document.querySelector(`#${id}`);
  if (element) element.textContent = value;
}

function renderScenario(key, animate = true) {
  activeScenario = key;
  const scenario = scenarios[key];
  buttons.forEach((button) => {
    const selected = button.dataset.scenario === key;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  setText("scenario-command", scenario.command);
  setText("output-title", scenario.title);
  setText("output-summary", scenario.summary);
  setText("output-action", scenario.action);
  const metricIds = ["one", "two", "three"];
  scenario.metrics.forEach((metric, index) => {
    setText(`metric-${metricIds[index]}-label`, metric[0]);
    setText(`metric-${metricIds[index]}-value`, metric[1]);
    setText(`metric-${metricIds[index]}-note`, metric[2]);
  });
  const deadline = document.querySelector("#deadline-sample strong");
  if (deadline) deadline.textContent = scenario.deadline;
  clearInterval(progressTimer);
  progressBar.max = scenario.progress.length;
  if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    progressBar.value = scenario.progress.length;
    progressLabel.textContent = scenario.progress.at(-1);
    output.classList.remove("loading");
    return;
  }
  output.classList.add("loading");
  progressBar.value = 0;
  let step = 0;
  progressLabel.textContent = scenario.progress[step];
  progressTimer = window.setInterval(() => {
    step += 1;
    progressBar.value = Math.min(scenario.progress.length, step + 1);
    progressLabel.textContent = scenario.progress[Math.min(step, scenario.progress.length - 1)];
    if (step >= scenario.progress.length - 1) {
      clearInterval(progressTimer);
      window.setTimeout(() => output.classList.remove("loading"), 180);
    }
  }, 520);
}

buttons.forEach((button) => {
  button.addEventListener("click", () => renderScenario(button.dataset.scenario));
});
runButton?.addEventListener("click", () => renderScenario(activeScenario));

const marquee = document.querySelector(".demo-marquee div");
if (marquee) marquee.insertAdjacentHTML("beforeend", marquee.innerHTML);

renderScenario(activeScenario, false);
