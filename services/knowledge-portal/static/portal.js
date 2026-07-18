document.addEventListener("click", async (event) => {
  const questionButton = event.target.closest("[data-question]");
  if (questionButton) {
    const question = document.querySelector('#assistant-form textarea[name="question"]');
    if (question) {
      question.value = questionButton.dataset.question;
      question.focus();
    }
    return;
  }
  const button = event.target.closest("[data-copy-target], [data-copy-config], [data-copy-value]");
  if (!button) return;

  let value = "";
  if (button.dataset.copyValue !== undefined) {
    value = button.dataset.copyValue;
  } else if (button.dataset.copyConfig !== undefined) {
    value = `JIAOTANG_KB_ENDPOINT=${window.location.origin}\nJIAOTANG_KB_MCP_URL=${window.location.origin}/mcp/\nJIAOTANG_KB_TOKEN=${button.dataset.token}`;
  } else {
    const target = document.querySelector(button.dataset.copyTarget);
    value = target?.textContent?.trim() || "";
  }
  if (!value) return;

  try {
    await navigator.clipboard.writeText(value);
    const original = button.textContent;
    button.textContent = "已复制";
    button.classList.add("copy-success");
    window.setTimeout(() => {
      button.textContent = original;
      button.classList.remove("copy-success");
    }, 1800);
  } catch {
    window.prompt("请复制以下内容", value);
  }
});

document.querySelector("#assistant-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const result = document.querySelector("#assistant-result");
  const answer = document.querySelector("#assistant-answer");
  const mode = document.querySelector("#assistant-result-mode");
  const sources = document.querySelector("#assistant-sources");
  submit.disabled = true;
  submit.textContent = "正在检索…";
  try {
    const response = await fetch("/assistant/answer", {method: "POST", body: new FormData(form)});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "答疑失败");
    answer.textContent = payload.answer;
    mode.textContent = payload.mode === "language-model" ? "大模型增强" : "免费知识检索";
    sources.replaceChildren();
    payload.sources.forEach((item) => {
      const row = document.createElement("span");
      row.textContent = `#${item.document_id} ${item.title}`;
      sources.appendChild(row);
    });
    result.hidden = false;
  } catch (error) {
    answer.textContent = error.message;
    mode.textContent = "需要检查";
    sources.replaceChildren();
    result.hidden = false;
  } finally {
    submit.disabled = false;
    submit.textContent = "开始答疑";
  }
});
