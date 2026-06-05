const state = {
  conversations: [],
  localSessions: [],
  activeSessionId: null,
};

const chat = document.querySelector("#chat");
const emptyState = document.querySelector("#emptyState");
const form = document.querySelector("#generateForm");
const promptInput = document.querySelector("#prompt");
const referenceInput = document.querySelector("#reference");
const fileChip = document.querySelector("#fileChip");
const ratioSelect = document.querySelector("#ratio");
const modelSelect = document.querySelector("#model");
const qualitySelect = document.querySelector("#quality");
const countSelect = document.querySelector("#count");
const submitBtn = document.querySelector("#submitBtn");
const sessionList = document.querySelector("#sessionList");
const assetGrid = document.querySelector("#assetGrid");
const assetCount = document.querySelector("#assetCount");
const clearHistoryBtn = document.querySelector("#clearHistoryBtn");
const settingsBtn = document.querySelector("#settingsBtn");
const settingsDialog = document.querySelector("#settingsDialog");
const settingsForm = document.querySelector("#settingsForm");
const closeSettingsBtn = document.querySelector("#closeSettingsBtn");
const apiBaseUrlInput = document.querySelector("#apiBaseUrl");
const apiKeyInput = document.querySelector("#apiKey");
const apiModelInput = document.querySelector("#apiModel");
const modelOptions = document.querySelector("#modelOptions");
const fetchModelsBtn = document.querySelector("#fetchModelsBtn");
const templateList = document.querySelector("#templateList");
const addTemplateBtn = document.querySelector("#addTemplateBtn");
const templateDialog = document.querySelector("#templateDialog");
const templateForm = document.querySelector("#templateForm");
const closeTemplateBtn = document.querySelector("#closeTemplateBtn");
const templateDialogTitle = document.querySelector("#templateDialogTitle");
const templateIdInput = document.querySelector("#templateId");
const templateTitleInput = document.querySelector("#templateTitle");
const templatePromptInput = document.querySelector("#templatePrompt");

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2600);
}

function clearChat() {
  chat.innerHTML = "";
}

function renderEmptyState() {
  clearChat();
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.innerHTML = `<div class="empty-icon">🖼</div><strong>还没有生成图片</strong><span>输入提示词后，结果会显示在这里</span>`;
  chat.appendChild(empty);
}

function ensureChat() {
  document.querySelectorAll(".empty-state").forEach((item) => item.remove());
}

function addPromptBubble(prompt) {
  ensureChat();
  const bubble = document.createElement("div");
  bubble.className = "prompt-bubble";
  bubble.textContent = prompt;
  chat.appendChild(bubble);
}

function addImageCard(src, prompt) {
  ensureChat();
  const card = document.createElement("article");
  card.className = "image-card";
  const img = document.createElement("img");
  img.src = src;
  img.alt = "生成图片";
  const actions = document.createElement("div");
  actions.className = "image-actions";
  actions.innerHTML = `
    <button type="button" data-action="ref">添加为参考</button>
    <button type="button" data-action="copy">复制链接</button>
    <button type="button" data-action="prompt">填回提示词</button>
  `;
  actions.querySelector('[data-action="ref"]').addEventListener("click", async () => {
    const file = await urlToFile(src);
    const dt = new DataTransfer();
    dt.items.add(file);
    referenceInput.files = dt.files;
    fileChip.textContent = file.name;
    showToast("已添加为参考图");
  });
  actions.querySelector('[data-action="copy"]').addEventListener("click", () => {
    navigator.clipboard.writeText(location.origin + src);
    showToast("图片链接已复制");
  });
  actions.querySelector('[data-action="prompt"]').addEventListener("click", () => {
    promptInput.value = prompt;
    showToast("提示词已填回");
  });
  card.append(img, actions);
  chat.appendChild(card);
  chat.scrollTop = chat.scrollHeight;
}

function addErrorCard(message) {
  ensureChat();
  const card = document.createElement("article");
  card.className = "error-card";
  const title = document.createElement("strong");
  title.textContent = "生成失败";
  const detail = document.createElement("pre");
  detail.textContent = message || "未知错误";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = "复制错误";
  copy.addEventListener("click", () => {
    navigator.clipboard.writeText(detail.textContent);
    showToast("错误信息已复制");
  });
  card.append(title, detail, copy);
  chat.appendChild(card);
  chat.scrollTop = chat.scrollHeight;
}

async function urlToFile(url) {
  const response = await fetch(url);
  const blob = await response.blob();
  return new File([blob], `reference_${Date.now()}.png`, { type: blob.type || "image/png" });
}

function addAsset(src, name = "图片") {
  const item = document.createElement("div");
  item.className = "asset";
  item.innerHTML = `
    <img src="${src}" alt="${name}">
    <div>
      <strong>${name}</strong><br>
      <button type="button" data-action="use">引用</button>
      <button type="button" data-action="delete">删除</button>
    </div>
  `;
  item.querySelector('[data-action="use"]').addEventListener("click", async () => {
    const file = await urlToFile(src);
    const dt = new DataTransfer();
    dt.items.add(file);
    referenceInput.files = dt.files;
    fileChip.textContent = file.name;
    showToast("已引用到参考图");
  });
  item.querySelector('[data-action="delete"]').addEventListener("click", async () => {
    if (!confirm("确定删除这张图片吗？")) return;
    const response = await fetch(`/api/images?path=${encodeURIComponent(src)}`, { method: "DELETE" });
    if (!response.ok) {
      showToast("删除图片失败");
      return;
    }
    await loadHistory();
    if (state.activeSessionId) openConversationById(state.activeSessionId);
    showToast("图片已删除");
  });
  assetGrid.prepend(item);
  assetCount.textContent = `${assetGrid.children.length} 张图片`;
}

function renderConversations(conversations) {
  sessionList.innerHTML = "";
  assetGrid.innerHTML = "";
  state.localSessions.forEach((session) => renderSessionCard(session, true));
  conversations.forEach((conversation, index) => {
    const imageCount = conversation.records.reduce((total, record) => total + record.image_paths.length, 0);
    renderSessionCard({
      id: conversation.id,
      title: conversation.title,
      subtitle: `${imageCount} 张 · ${conversation.updated_at}`,
      deletable: true,
      active: state.activeSessionId === conversation.id || (!state.activeSessionId && index === 0),
      open: () => {
        openConversation(conversation);
      },
    });
    conversation.records.forEach((record) => {
      record.image_paths.forEach((src, imgIndex) => addAsset(src, `图片${record.id}-${imgIndex + 1}`));
    });
  });
  assetCount.textContent = `${assetGrid.children.length} 张图片`;
}

function openConversation(conversation) {
  state.activeSessionId = conversation.id;
  setActiveSession(state.activeSessionId);
  clearChat();
  conversation.records.forEach((record) => {
    addPromptBubble(record.prompt);
    record.image_paths.forEach((src) => addImageCard(src, record.prompt));
  });
  if (!conversation.records.length) renderEmptyState();
  promptInput.value = conversation.records.at(-1)?.prompt || "";
}

function openConversationById(conversationId) {
  const conversation = state.conversations.find((item) => item.id === conversationId);
  if (conversation) openConversation(conversation);
}

function renderSessionCard(session, prepend = false) {
  const card = document.createElement("div");
  card.className = `session-card ${session.active || state.activeSessionId === session.id ? "active" : ""}`;
  card.dataset.sessionId = session.id;
  card.innerHTML = `
    <div class="session-text">
      <strong>${session.title}</strong>
      <span>${session.subtitle}</span>
    </div>
    <button type="button" class="session-delete" title="删除">×</button>
  `;
  const deleteButton = card.querySelector(".session-delete");
  deleteButton.hidden = session.deletable === false ? true : false;
  deleteButton.addEventListener("click", async (event) => {
    event.stopPropagation();
    await deleteSession(session.id);
  });
  card.addEventListener("click", () => {
    state.activeSessionId = session.id;
    setActiveSession(session.id);
    if (session.open) {
      session.open();
    } else {
      clearChat();
      session.messages.forEach((message) => {
        if (message.type === "prompt") addPromptBubble(message.prompt);
        if (message.type === "image") addImageCard(message.src, message.prompt);
        if (message.type === "error") addErrorCard(message.message);
      });
      if (!session.messages.length) renderEmptyState();
    }
  });
  if (prepend) {
    sessionList.prepend(card);
  } else {
    sessionList.appendChild(card);
  }
}

async function deleteSession(sessionId) {
  if (!confirm("确定删除这个会话吗？会删除该会话内的图片文件。")) return;
  const localIndex = state.localSessions.findIndex((session) => session.id === sessionId);
  if (localIndex >= 0) {
    state.localSessions.splice(localIndex, 1);
    if (state.activeSessionId === sessionId) {
      state.activeSessionId = null;
      renderEmptyState();
    }
    renderConversations(state.conversations);
    showToast("会话已删除");
    return;
  }
  const response = await fetch(`/api/conversations/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  if (!response.ok) {
    showToast("删除会话失败");
    return;
  }
  if (state.activeSessionId === sessionId) {
    state.activeSessionId = null;
    renderEmptyState();
  }
  await loadHistory();
  showToast("会话已删除");
}

function setActiveSession(sessionId) {
  document.querySelectorAll(".session-card").forEach((card) => {
    card.classList.toggle("active", card.dataset.sessionId === sessionId);
  });
}

function createLocalSession(id = `local-${Date.now()}`) {
  const session = {
    id,
    title: "新对话",
    subtitle: "0 张 · 刚刚",
    active: true,
    messages: [],
  };
  state.localSessions.forEach((item) => (item.active = false));
  state.localSessions.unshift(session);
  state.activeSessionId = session.id;
  renderConversations(state.conversations);
  renderEmptyState();
  promptInput.value = "";
  referenceInput.value = "";
  fileChip.textContent = "未选择参考图";
  return session;
}

function activeLocalSession() {
  return state.localSessions.find((session) => session.id === state.activeSessionId) || null;
}

function ensureSubmitSession() {
  let session = activeLocalSession();
  if (session) return session;
  const conversation = state.conversations.find((item) => item.id === state.activeSessionId);
  if (conversation) {
    return {
      id: conversation.id,
      title: conversation.title,
      subtitle: "生成中...",
      messages: [],
      persisted: true,
    };
  }
  if (state.activeSessionId) {
    session = createLocalSession(state.activeSessionId);
    return session;
  }
  return createLocalSession();
}

async function loadHistory() {
  const response = await fetch("/api/conversations");
  state.conversations = await response.json();
  state.localSessions = state.localSessions.filter((local) => !state.conversations.some((conversation) => conversation.id === local.id));
  renderConversations(state.conversations);
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const status = await response.json();
  document.querySelector("#notice").textContent = status.notice;
  if (status.models?.length) {
    setAvailableModels(status.models, status.settings?.model || status.models[0]);
  }
  if (status.settings?.model) {
    setModelSelectValue(status.settings.model);
  }
}

function setModelSelectValue(model) {
  if (!model) return;
  const exists = [...modelSelect.options].some((option) => option.value === model);
  if (!exists) {
    modelSelect.appendChild(new Option(model, model));
  }
  modelSelect.value = model;
}

function setAvailableModels(models, selected = "") {
  const unique = [...new Set(models.filter(Boolean))];
  const current = selected || apiModelInput.value || modelSelect.value || "gpt-image-2";
  modelSelect.innerHTML = "";
  modelOptions.innerHTML = "";
  unique.forEach((model) => {
    modelSelect.appendChild(new Option(model, model));
    const option = document.createElement("option");
    option.value = model;
    modelOptions.appendChild(option);
  });
  setModelSelectValue(current);
  apiModelInput.value = current;
}

async function loadSettings() {
  const response = await fetch("/api/settings");
  if (!response.ok) throw new Error("读取设置失败");
  const settings = await response.json();
  apiBaseUrlInput.value = settings.base_url || "";
  apiKeyInput.value = settings.api_key || "";
  apiModelInput.value = settings.model || "gpt-image-2";
  setModelSelectValue(settings.model || "gpt-image-2");
}

async function saveSettings() {
  const payload = {
    base_url: apiBaseUrlInput.value.trim(),
    api_key: apiKeyInput.value.trim(),
    model: apiModelInput.value.trim() || "gpt-image-2",
  };
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "保存设置失败");
  setModelSelectValue(data.model);
  showToast("设置已保存");
}

async function fetchModels() {
  const payload = {
    base_url: apiBaseUrlInput.value.trim(),
    api_key: apiKeyInput.value.trim(),
  };
  fetchModelsBtn.disabled = true;
  fetchModelsBtn.textContent = "获取中...";
  try {
    const response = await fetch("/api/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "获取模型失败");
    if (!data.models?.length) throw new Error("接口没有返回模型列表");
    setAvailableModels(data.models, data.models.includes(apiModelInput.value) ? apiModelInput.value : data.models[0]);
    showToast(`已获取 ${data.models.length} 个模型`);
  } finally {
    fetchModelsBtn.disabled = false;
    fetchModelsBtn.textContent = "获取模型";
  }
}

async function loadTemplates() {
  const response = await fetch("/api/templates");
  if (!response.ok) {
    showToast("读取模板失败");
    return;
  }
  const templates = await response.json();
  renderTemplates(templates);
}

function renderTemplates(templates) {
  templateList.innerHTML = "";
  if (!templates.length) {
    templateList.innerHTML = `<div class="template-card"><p>还没有模板，点击新增创建一个。</p></div>`;
    return;
  }
  templates.forEach((template) => {
    const card = document.createElement("div");
    card.className = "template-card";
    card.innerHTML = `
      <strong>${escapeHtml(template.title)}</strong>
      <p>${escapeHtml(template.prompt)}</p>
      <div class="template-actions">
        <button type="button" data-action="use">使用</button>
        <button type="button" data-action="edit">编辑</button>
        <button type="button" class="danger" data-action="delete">删除</button>
      </div>
    `;
    card.querySelector('[data-action="use"]').addEventListener("click", () => {
      promptInput.value = template.prompt;
      promptInput.focus();
      showToast("模板已填入输入框");
    });
    card.querySelector('[data-action="edit"]').addEventListener("click", () => openTemplateDialog(template));
    card.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!confirm("确定删除这个提示词模板吗？")) return;
      const response = await fetch(`/api/templates/${encodeURIComponent(template.id)}`, { method: "DELETE" });
      if (!response.ok) {
        showToast("删除模板失败");
        return;
      }
      await loadTemplates();
      showToast("模板已删除");
    });
    templateList.appendChild(card);
  });
}

function openTemplateDialog(template = null) {
  templateDialogTitle.textContent = template ? "编辑模板" : "新增模板";
  templateIdInput.value = template?.id || "";
  templateTitleInput.value = template?.title || "";
  templatePromptInput.value = template?.prompt || "";
  templateDialog.showModal();
}

async function saveTemplate() {
  const id = templateIdInput.value;
  const payload = {
    id,
    title: templateTitleInput.value.trim(),
    prompt: templatePromptInput.value.trim(),
  };
  const url = id ? `/api/templates/${encodeURIComponent(id)}` : "/api/templates";
  const method = id ? "PUT" : "POST";
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "保存模板失败");
  await loadTemplates();
  showToast("模板已保存");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

referenceInput.addEventListener("change", () => {
  fileChip.textContent = referenceInput.files[0]?.name || "未选择参考图";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = promptInput.value.trim();
  if (!prompt) {
    showToast("请先输入提示词");
    return;
  }
  let session = ensureSubmitSession();
  const [width, height] = ratioSelect.value.split("x");
  const data = new FormData();
  data.append("conversation_id", session.id);
  data.append("prompt", prompt);
  data.append("model", modelSelect.value);
  data.append("quality", qualitySelect.value);
  data.append("count", countSelect.value);
  data.append("width", width);
  data.append("height", height);
  if (referenceInput.files[0]) data.append("reference", referenceInput.files[0]);

  submitBtn.disabled = true;
  submitBtn.textContent = "生成中";
  session.title = prompt.slice(0, 22) || "新对话";
  session.subtitle = "生成中...";
  session.messages.push({ type: "prompt", prompt });
  if (!session.persisted) renderConversations(state.conversations);
  addPromptBubble(prompt);
  try {
    const response = await fetch("/api/generate", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "生成失败");
    payload.images.forEach((src) => {
      addImageCard(src, prompt);
      addAsset(src, "生成图");
      session.messages.push({ type: "image", src, prompt });
    });
    session.subtitle = `${payload.images.length} 张 · 刚刚`;
    state.localSessions = state.localSessions.filter((item) => item.id !== session.id);
    state.activeSessionId = payload.conversation_id || session.id;
    await loadHistory();
    openConversationById(state.activeSessionId);
  } catch (error) {
    const message = error.message || "生成失败";
    session.subtitle = "生成失败";
    session.messages.push({ type: "error", message });
    if (!session.persisted) renderConversations(state.conversations);
    addErrorCard(message);
    showToast("生成失败，详情已显示在中间区域");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "生成";
  }
});

clearHistoryBtn.addEventListener("click", async () => {
  if (!confirm("确定清空历史记录吗？图片文件不会删除。")) return;
  await fetch("/api/history", { method: "DELETE" });
  await loadHistory();
  showToast("历史已清空");
});

settingsBtn.addEventListener("click", async () => {
  try {
    await loadSettings();
    settingsDialog.showModal();
  } catch (error) {
    showToast(error.message || "读取设置失败");
  }
});

closeSettingsBtn.addEventListener("click", () => settingsDialog.close());
fetchModelsBtn.addEventListener("click", async () => {
  try {
    await fetchModels();
  } catch (error) {
    showToast(error.message || "获取模型失败");
  }
});

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveSettings();
    settingsDialog.close();
  } catch (error) {
    showToast(error.message || "保存设置失败");
  }
});

addTemplateBtn.addEventListener("click", () => openTemplateDialog());
closeTemplateBtn.addEventListener("click", () => templateDialog.close());
templateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveTemplate();
    templateDialog.close();
  } catch (error) {
    showToast(error.message || "保存模板失败");
  }
});

document.querySelector("#newChatBtn").addEventListener("click", () => {
  createLocalSession();
});

loadStatus();
loadHistory();
loadTemplates();
