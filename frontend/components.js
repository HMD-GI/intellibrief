export function renderTopics(container, topics, activeTopics, onToggle) {
  container.innerHTML = topics
    .map(
      (topic) =>
        `<button class="chip ${activeTopics.includes(topic) ? "active" : ""}" data-topic="${topic}">${topic}</button>`,
    )
    .join("");

  container.querySelectorAll("[data-topic]").forEach((button) => {
    button.addEventListener("click", () => onToggle(button.dataset.topic));
  });
}

export function renderBriefTable(container, items, onView, onDelete) {
  if (!items || !items.length) {
    container.innerHTML = `<div class="empty">暂无简报</div>`;
    return;
  }

  container.innerHTML = `
    <div class="table-row table-head">
      <div>日期</div><div>标题</div><div>类型</div><div>操作</div>
    </div>
    ${items
      .map(
        (item) => `
        <div class="table-row">
          <div>${item.date}</div>
          <div>${item.title}</div>
          <div>${item.type || "daily"}</div>
          <div class="row-actions">
            <button class="secondary-btn" data-action="view" data-date="${item.date}">查看</button>
            <button class="danger-btn" data-action="delete" data-date="${item.date}">删除</button>
          </div>
        </div>
      `,
      )
      .join("")}
  `;

  container.querySelectorAll('[data-action="view"]').forEach((button) => {
    button.addEventListener("click", () => onView(button.dataset.date));
  });
  container.querySelectorAll('[data-action="delete"]').forEach((button) => {
    button.addEventListener("click", () => onDelete(button.dataset.date));
  });
}

export function showToast(el, text) {
  el.textContent = text;
  el.classList.remove("hidden");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), 2200);
}
