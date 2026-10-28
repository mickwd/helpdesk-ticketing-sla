// Frontend sin build: router por hash, fetch a la API y Chart.js para el dashboard.
"use strict";

const state = { token: localStorage.getItem("token"), user: null, timers: [], charts: [] };

const LABELS = {
  status: {
    nuevo: "Nuevo", asignado: "Asignado", en_progreso: "En progreso",
    en_espera_usuario: "En espera del usuario", resuelto: "Resuelto", cerrado: "Cerrado",
  },
  sla: {
    en_curso: "En curso", advertencia: "Advertencia", incumplido: "Incumplido",
    pausado: "Pausado", cumplido: "Cumplido",
  },
  event: {
    creado: "Creado", clasificado: "Clasificado", estado: "Cambio de estado", asignacion: "Asignación",
    escalamiento: "Escalamiento", desescalamiento: "Desescalamiento", prioridad: "Prioridad",
    categoria: "Categoría", comentario: "Comentario", adjunto: "Adjunto",
    primera_respuesta: "Primera respuesta", sla_advertencia: "Advertencia de SLA",
    sla_incumplido: "SLA incumplido",
  },
  role: {
    solicitante: "Solicitante", agente_n1: "Agente N1", agente_n2: "Agente N2",
    agente_n3: "Agente N3", supervisor: "Supervisión",
  },
};
const STAFF = ["agente_n1", "agente_n2", "agente_n3", "supervisor"];

// ------------------------------------------------------------------ utilidades
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
const $ = (sel, root = document) => root.querySelector(sel);
const isStaff = () => state.user && STAFF.includes(state.user.role);
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("es-AR", {
  timeZone: "America/Argentina/Buenos_Aires", dateStyle: "short", timeStyle: "short",
}) : "—");

function fmtDuration(seconds) {
  const s = Math.abs(Math.round(seconds));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m ${s % 60}s`;
}

function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (error ? " error" : "");
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.hidden = true), 4000);
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    logout();
    throw new Error("La sesión venció, ingresá nuevamente");
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join(". ");
    throw new Error(detail || `Error ${res.status}`);
  }
  return data;
}

// --------------------------------------------------------------- badges de SLA
function slaColor(sla) {
  if (sla.state === "incumplido") return "rojo";
  if (sla.state === "advertencia") return "amarillo";
  if (sla.state === "pausado" || sla.state === "cumplido") return "gris";
  return "verde";
}

function slaText(sla) {
  if (sla.state === "pausado") return "⏸ pausado";
  if (sla.state === "cumplido") return "✔ cumplido";
  if (sla.state === "incumplido" && !sla.due_at) return "✖ incumplido";
  if (!sla.due_at) return LABELS.sla[sla.state];
  const diff = (new Date(sla.due_at) - Date.now()) / 1000;
  if (sla.breached || diff < 0) return `✖ vencido hace ${fmtDuration(diff)}`;
  return `⏱ ${fmtDuration(diff)}`;
}

function slaBadge(sla) {
  const due = sla.due_at ? ` data-due="${esc(sla.due_at)}"` : "";
  return `<span class="badge sla ${slaColor(sla)}" data-sla='${esc(JSON.stringify(sla))}'${due}
    title="${esc(LABELS.sla[sla.state])} · ${Math.round(sla.percent * 100)}% consumido">${slaText(sla)}</span>`;
}

function startCountdowns() {
  // Las cuentas regresivas se refrescan cada segundo contra la fecha de vencimiento
  state.timers.push(setInterval(() => {
    document.querySelectorAll(".sla[data-due]").forEach((el) => {
      const sla = JSON.parse(el.dataset.sla);
      if (["en_curso", "advertencia"].includes(sla.state)) el.textContent = slaText(sla);
    });
  }, 1000));
}

function slaBar(title, sla) {
  const pct = Math.min(100, Math.round(sla.percent * 100));
  return `<div style="margin-bottom:14px">
    <div class="row" style="align-items:center"><strong>${title}</strong>
      <span style="text-align:right">${slaBadge(sla)}</span></div>
    <div class="bar" style="margin-top:6px"><div class="${slaColor(sla)}" style="width:${pct}%"></div></div>
    <div class="small muted" style="margin-top:4px">${pct}% de ${fmtDuration(sla.target_seconds)} hábiles ·
      vence ${fmtDate(sla.due_at)}</div></div>`;
}

// ---------------------------------------------------------------------- vistas
function cleanup() {
  state.timers.forEach(clearInterval);
  state.timers = [];
  state.charts.forEach((c) => c.destroy());
  state.charts = [];
}

function renderLogin() {
  $("#topbar").hidden = true;
  const demo = [
    ["supervisor@example.com", "Supervisión"], ["n1.martin@example.com", "Agente N1"],
    ["n2.sofia@example.com", "Agente N2"], ["n3.lucia@example.com", "Agente N3"],
    ["ana.perez@example.com", "Solicitante"],
  ];
  $("#view").innerHTML = `
    <div class="panel login">
      <h1>Ingresar</h1>
      <form id="login-form">
        <label>Email</label><input name="username" type="email" required autocomplete="username">
        <label>Contraseña</label><input name="password" type="password" required autocomplete="current-password">
        <div style="margin-top:16px"><button type="submit">Ingresar</button></div>
      </form>
      <div class="demo-users muted">Usuarios de demo (contraseña <code>Demo1234!</code>):<br>
        ${demo.map(([e, r]) => `<code data-email="${e}">${e}</code> — ${r}`).join("<br>")}</div>
    </div>`;
  document.querySelectorAll("[data-email]").forEach((el) => el.addEventListener("click", () => {
    $("[name=username]").value = el.dataset.email;
    $("[name=password]").value = "Demo1234!";
  }));
  $("#login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const body = new URLSearchParams(new FormData(ev.target));
      const data = await api("/api/auth/login", { method: "POST", body });
      state.token = data.access_token;
      localStorage.setItem("token", state.token);
      await loadUser();
      location.hash = "#/tickets";
    } catch (err) { toast(err.message, true); }
  });
}

async function renderTickets() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const filters = {
    status: params.get("status") || "", priority: params.get("priority") || "",
    level: params.get("level") || "", sla: params.get("sla") || "", q: params.get("q") || "",
    open_only: params.get("open_only") ?? "true", offset: Number(params.get("offset") || 0),
  };
  const opt = (values, current, labels = {}) => ['<option value="">Todos</option>']
    .concat(values.map((v) => `<option value="${v}" ${v === current ? "selected" : ""}>${labels[v] || v}</option>`))
    .join("");
  $("#view").innerHTML = `
    <h1>Tickets</h1>
    <div class="panel">
      <form id="filters" class="row">
        <div><label>Buscar</label><input name="q" value="${esc(filters.q)}" placeholder="Título o descripción"></div>
        <div><label>Estado</label><select name="status">${opt(Object.keys(LABELS.status), filters.status, LABELS.status)}</select></div>
        <div><label>Prioridad</label><select name="priority">${opt(["P1", "P2", "P3", "P4"], filters.priority)}</select></div>
        <div><label>Nivel</label><select name="level">${opt(["N1", "N2", "N3"], filters.level)}</select></div>
        <div><label>SLA</label><select name="sla">${opt(Object.keys(LABELS.sla), filters.sla, LABELS.sla)}</select></div>
        <div><label>Mostrar</label><select name="open_only">
          <option value="true" ${filters.open_only === "true" ? "selected" : ""}>Solo abiertos</option>
          <option value="false" ${filters.open_only === "false" ? "selected" : ""}>Todos</option></select></div>
        <div style="flex:0"><button type="submit">Filtrar</button></div>
      </form>
    </div>
    <div class="panel"><div id="ticket-table" class="muted">Cargando…</div></div>`;
  $("#filters").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const fd = new URLSearchParams();
    for (const [k, v] of new FormData(ev.target)) if (v) fd.set(k, v);
    location.hash = `#/tickets?${fd}`;
  });

  const query = new URLSearchParams({ limit: 25, offset: filters.offset });
  for (const k of ["status", "priority", "level", "sla", "q", "open_only"]) if (filters[k]) query.set(k, filters[k]);
  const page = await api(`/api/tickets?${query}`);
  if (!page.items.length) {
    $("#ticket-table").innerHTML = "No hay tickets con esos filtros.";
    return;
  }
  $("#ticket-table").innerHTML = `
    <table><thead><tr><th>#</th><th>Título</th><th>Prioridad</th><th>Estado</th><th>Nivel</th>
      <th>Asignado</th><th>SLA resolución</th><th>Creado</th></tr></thead>
    <tbody>${page.items.map((t) => `
      <tr data-id="${t.id}">
        <td>${t.id}</td><td>${esc(t.title)}<div class="small muted">${esc(t.category)} · ${esc(t.specialty)}</div></td>
        <td><span class="badge ${t.priority}">${t.priority}</span></td>
        <td>${LABELS.status[t.status]}</td><td>${t.level}${t.escalation_count ? ` <span class="small muted">↑${t.escalation_count}</span>` : ""}</td>
        <td>${t.assignee ? esc(t.assignee.full_name) : '<span class="muted">Sin asignar</span>'}</td>
        <td>${slaBadge(t.sla_resolution)}</td><td class="small">${fmtDate(t.created_at)}</td>
      </tr>`).join("")}</tbody></table>
    <div class="pager"><span class="muted">${filters.offset + 1}–${filters.offset + page.items.length} de ${page.total}</span>
      <button class="secondary" id="prev" ${filters.offset === 0 ? "disabled" : ""}>Anterior</button>
      <button class="secondary" id="next" ${filters.offset + 25 >= page.total ? "disabled" : ""}>Siguiente</button></div>`;
  document.querySelectorAll("tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => (location.hash = `#/tickets/${tr.dataset.id}`)));
  const go = (delta) => {
    params.set("offset", Math.max(0, filters.offset + delta));
    location.hash = `#/tickets?${params}`;
  };
  $("#prev").addEventListener("click", () => go(-25));
  $("#next").addEventListener("click", () => go(25));
  startCountdowns();
  // Refresco del listado cada minuto (el router limpia el timer al navegar)
  state.timers.push(setInterval(router, 60000));
}

function timelineItem(e) {
  const actor = e.actor ? esc(e.actor.full_name) : "Sistema";
  const change = e.from_value || e.to_value
    ? ` <span class="muted">${esc(e.from_value || "")}${e.from_value ? " → " : ""}${esc(e.to_value || "")}</span>` : "";
  return `<li class="${e.event_type}"><strong>${LABELS.event[e.event_type] || e.event_type}</strong>${change}
    <div class="when">${fmtDate(e.created_at)} · ${actor}</div>
    ${e.message && e.event_type !== "comentario" ? `<div>${esc(e.message)}</div>` : ""}</li>`;
}

async function renderTicket(id) {
  const t = await api(`/api/tickets/${id}`);
  const staff = isStaff();
  const transitions = t.allowed_transitions.map((s) =>
    `<button class="${s === "resuelto" ? "" : "secondary"}" data-transition="${s}">${LABELS.status[s]}</button>`).join("");
  const open = !["resuelto", "cerrado"].includes(t.status);
  $("#view").innerHTML = `
    <p><a href="#/tickets">← Volver</a></p>
    <h1>#${t.id} ${esc(t.title)}</h1>
    <div class="grid grid-2">
      <div>
        <div class="panel">
          <div class="actions" style="margin-bottom:12px">
            <span class="badge ${t.priority}">${t.priority}</span>
            <span class="badge">${LABELS.status[t.status]}</span>
            <span class="badge">${t.level}</span>
            <span class="badge">${esc(t.category)}</span>
          </div>
          <div class="comment">${esc(t.description)}</div>
          ${t.resolution ? `<h2 style="margin-top:16px">Resolución</h2><div class="comment">${esc(t.resolution)}</div>` : ""}
        </div>
        <div class="panel">
          <h2>Conversación</h2>
          ${t.comments.length ? t.comments.map((c) => `
            <div class="comment ${c.is_internal ? "internal" : ""}">
              <div class="small muted">${esc(c.author.full_name)} · ${fmtDate(c.created_at)}${c.is_internal ? " · nota interna" : ""}</div>
              ${esc(c.body)}</div>`).join("") : '<p class="muted">Sin comentarios.</p>'}
          ${t.status !== "cerrado" ? `
          <form id="comment-form" style="margin-top:12px">
            <textarea name="body" required placeholder="Escribí un comentario…"></textarea>
            <div class="row" style="margin-top:8px;align-items:center">
              ${staff ? '<label style="margin:0;font-weight:400"><input type="checkbox" name="internal" style="width:auto"> Nota interna</label>' : "<span></span>"}
              <div style="flex:0"><button type="submit">Comentar</button></div>
            </div>
          </form>` : ""}
        </div>
        <div class="panel"><h2>Historial (auditoría)</h2><ul class="timeline">${t.events.map(timelineItem).join("")}</ul></div>
      </div>
      <div>
        <div class="panel">
          <h2>SLA</h2>
          ${slaBar("Primera respuesta", t.sla_response)}
          ${slaBar("Resolución", t.sla_resolution)}
        </div>
        <div class="panel">
          <dl class="kv">
            <dt>Solicitante</dt><dd>${esc(t.requester.full_name)}</dd>
            <dt>Asignado</dt><dd>${t.assignee ? esc(t.assignee.full_name) : "Sin asignar"}</dd>
            <dt>Impacto/urgencia</dt><dd>${esc(t.impact)} / ${esc(t.urgency)}</dd>
            <dt>Especialidad</dt><dd>${esc(t.specialty)}</dd>
            <dt>Clasificación</dt><dd>${esc(t.classification_source)}${t.classification_rule ? ` (${esc(t.classification_rule)})` : ""}</dd>
            <dt>Escalamientos</dt><dd>${t.escalation_count}</dd>
            <dt>Creado</dt><dd>${fmtDate(t.created_at)}</dd>
            <dt>Primera resp.</dt><dd>${fmtDate(t.first_responded_at)}</dd>
            <dt>Resuelto</dt><dd>${fmtDate(t.resolved_at)}</dd>
          </dl>
        </div>
        ${transitions ? `<div class="panel"><h2>Acciones</h2>
          <div class="actions">${transitions}</div>
          <div id="resolution-box" hidden><label>Solución aplicada</label><textarea id="resolution"></textarea>
            <button id="confirm-resolve" style="margin-top:8px">Confirmar resolución</button></div></div>` : ""}
        ${staff && open && t.allowed_transitions.length ? `<div class="panel"><h2>Escalamiento</h2>
          <label>Motivo (obligatorio)</label><textarea id="reason" placeholder="Mínimo 10 caracteres"></textarea>
          <div class="actions" style="margin-top:8px">
            ${t.level !== "N3" ? '<button class="danger" id="escalate">Escalar ↑</button>' : ""}
            ${t.level !== "N1" && state.user.role !== "agente_n1" ? '<button class="secondary" id="deescalate">Desescalar ↓</button>' : ""}
          </div>
          <label>Reasignar a</label><div class="row"><select id="assignee"><option value="">Cargando…</option></select>
            <div style="flex:0"><button class="secondary" id="assign">Asignar</button></div></div></div>` : ""}
        ${t.suggested_articles.length ? `<div class="panel"><h2>Artículos sugeridos</h2>
          ${t.suggested_articles.map((a) => `<div><a href="#/kb/${a.id}">${esc(a.title)}</a>
            <div class="small muted">coincide: ${a.matched.map(esc).join(", ")}</div></div>`).join("")}</div>` : ""}
        <div class="panel"><h2>Adjuntos</h2>
          ${t.attachments.map((a) => `<div class="small">📎 ${esc(a.filename)} <span class="muted">(${Math.ceil(a.size_bytes / 1024)} KB)</span></div>`).join("") || '<p class="muted small">Sin adjuntos.</p>'}
          ${t.status !== "cerrado" ? '<input type="file" id="file" style="margin-top:8px">' : ""}
        </div>
      </div>
    </div>`;

  const reload = () => renderTicket(id);
  const run = async (fn, ok) => {
    try { await fn(); toast(ok); await reload(); } catch (err) { toast(err.message, true); }
  };
  document.querySelectorAll("[data-transition]").forEach((btn) => btn.addEventListener("click", () => {
    const target = btn.dataset.transition;
    if (target === "resuelto") { $("#resolution-box").hidden = false; return; }
    run(() => api(`/api/tickets/${id}/transition`, { method: "POST", json: { status: target } }),
      `Estado: ${LABELS.status[target]}`);
  }));
  $("#confirm-resolve")?.addEventListener("click", () => run(() => api(`/api/tickets/${id}/transition`, {
    method: "POST", json: { status: "resuelto", resolution: $("#resolution").value },
  }), "Ticket resuelto"));
  $("#comment-form")?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    run(() => api(`/api/tickets/${id}/comments`, {
      method: "POST", json: { body: fd.get("body"), internal: fd.get("internal") === "on" },
    }), "Comentario agregado");
  });
  $("#escalate")?.addEventListener("click", () => run(() => api(`/api/tickets/${id}/escalate`, {
    method: "POST", json: { reason: $("#reason").value },
  }), "Ticket escalado"));
  $("#deescalate")?.addEventListener("click", () => run(() => api(`/api/tickets/${id}/deescalate`, {
    method: "POST", json: { reason: $("#reason").value },
  }), "Ticket desescalado"));
  $("#file")?.addEventListener("change", (ev) => {
    const body = new FormData();
    body.append("file", ev.target.files[0]);
    run(() => api(`/api/tickets/${id}/attachments`, { method: "POST", body }), "Adjunto cargado");
  });
  if ($("#assignee")) {
    const agents = await api("/api/users/agents");
    const role = `agente_${t.level.toLowerCase()}`;
    $("#assignee").innerHTML = agents.filter((a) => a.role === role).map((a) =>
      `<option value="${a.id}" ${t.assignee && t.assignee.id === a.id ? "selected" : ""}>${esc(a.full_name)} (${a.specialties.join(", ")})</option>`).join("");
    $("#assign").addEventListener("click", () => run(() => api(`/api/tickets/${id}/assign`, {
      method: "POST", json: { assignee_id: Number($("#assignee").value) },
    }), "Ticket reasignado"));
  }
  startCountdowns();
}

const MATRIX = {
  alto: { alta: "P1", media: "P2", baja: "P3" },
  medio: { alta: "P2", media: "P3", baja: "P4" },
  bajo: { alta: "P3", media: "P4", baja: "P4" },
};

function renderNew() {
  $("#view").innerHTML = `
    <h1>Nuevo ticket</h1>
    <div class="grid grid-2">
      <form class="panel" id="new-form">
        <label>Título</label><input name="title" required minlength="5" maxlength="200" placeholder="Ej.: La VPN no conecta desde mi casa">
        <label>Descripción</label><textarea name="description" required minlength="10" placeholder="Qué pasa, desde cuándo, a quién afecta, mensajes de error…"></textarea>
        <div class="row">
          <div><label>Impacto</label><select name="impact">
            <option value="bajo">Bajo — solo a mí</option><option value="medio" selected>Medio — a mi equipo</option>
            <option value="alto">Alto — a toda el área o clientes</option></select></div>
          <div><label>Urgencia</label><select name="urgency">
            <option value="baja">Baja — puedo seguir trabajando</option><option value="media" selected>Media — trabajo con dificultad</option>
            <option value="alta">Alta — no puedo trabajar</option></select></div>
        </div>
        <p>Prioridad calculada: <span id="prio" class="badge P3">P3</span></p>
        <button type="submit">Crear ticket</button>
      </form>
      <div>
        <div class="panel"><h2>Clasificación sugerida</h2><div id="classify" class="muted">Escribí el título para ver la sugerencia.</div></div>
        <div class="panel"><h2>Quizás te sirva</h2><div id="kb" class="muted small">Sin sugerencias por ahora.</div></div>
      </div>
    </div>`;
  const form = $("#new-form");
  const updatePriority = () => {
    const p = MATRIX[form.impact.value][form.urgency.value];
    $("#prio").textContent = p;
    $("#prio").className = `badge ${p}`;
  };
  let timer;
  const preview = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (form.title.value.length < 3) return;
      try {
        const c = await api("/api/classify", { method: "POST", json: {
          title: form.title.value, description: form.description.value,
        } });
        $("#classify").innerHTML = `<dl class="kv"><dt>Categoría</dt><dd>${esc(c.category)}</dd>
          <dt>Especialidad</dt><dd>${esc(c.specialty)}</dd><dt>Nivel inicial</dt><dd>${c.level}</dd>
          <dt>Origen</dt><dd>${esc(c.source)}${c.rule ? ` (${esc(c.rule)})` : ""}</dd>
          ${c.matched.length ? `<dt>Coincidencias</dt><dd>${c.matched.map(esc).join(", ")}</dd>` : ""}</dl>`;
        $("#kb").innerHTML = c.suggested_articles.length
          ? c.suggested_articles.map((a) => `<div><a href="#/kb/${a.id}">${esc(a.title)}</a></div>`).join("")
          : "Sin sugerencias por ahora.";
      } catch (err) { /* la vista previa es opcional */ }
    }, 400);
  };
  form.impact.addEventListener("change", updatePriority);
  form.urgency.addEventListener("change", updatePriority);
  form.title.addEventListener("input", preview);
  form.description.addEventListener("input", preview);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const data = await api("/api/tickets", { method: "POST", json: Object.fromEntries(new FormData(form)) });
      toast(`Ticket #${data.ticket.id} creado (${data.ticket.priority})`);
      location.hash = `#/tickets/${data.ticket.id}`;
    } catch (err) { toast(err.message, true); }
  });
}

async function renderArticle(id) {
  const a = await api(`/api/kb/articles/${id}`);
  $("#view").innerHTML = `<p><a href="javascript:history.back()">← Volver</a></p>
    <div class="panel"><h1>${esc(a.title)}</h1>
    <p class="small muted">${esc(a.category)} · ${esc(a.specialty || "general")} · palabras clave: ${a.keyword_list.map(esc).join(", ")}</p>
    <div class="comment">${esc(a.body)}</div>
    ${a.ticket_ids.length ? `<p class="small">Tickets relacionados: ${a.ticket_ids.map((t) => `<a href="#/tickets/${t}">#${t}</a>`).join(" ")}</p>` : ""}
    </div>`;
}

async function renderNotifications() {
  const items = await api("/api/notifications");
  $("#view").innerHTML = `<h1>Notificaciones</h1><div class="panel">${items.length ? items.map((n) => `
    <div style="padding:10px 0;border-bottom:1px solid var(--border)">
      <strong>${esc(n.subject)}</strong> ${n.is_read ? "" : '<span class="badge sla amarillo">nueva</span>'}
      <div class="small muted">${fmtDate(n.created_at)} · ${esc(n.kind)}</div><div>${esc(n.body)}</div>
      ${n.ticket_id ? `<a href="#/tickets/${n.ticket_id}" data-read="${n.id}">Ver ticket #${n.ticket_id}</a>` : ""}
    </div>`).join("") : '<p class="muted">No tenés notificaciones.</p>'}</div>`;
  document.querySelectorAll("[data-read]").forEach((el) => el.addEventListener("click", () =>
    api(`/api/notifications/${el.dataset.read}/read`, { method: "POST" }).catch(() => {})));
}

function kpi(label, value, suffix = "") {
  return `<div class="panel kpi"><div class="label">${label}</div>
    <div class="value">${value ?? "—"}${value != null ? suffix : ""}</div></div>`;
}

function chart(id, config) {
  if (!window.Chart) return;
  state.charts.push(new Chart(document.getElementById(id), config));
}

async function renderDashboard() {
  const m = await api("/api/metrics/overview");
  $("#view").innerHTML = `
    <h1>Métricas</h1>
    <div class="grid grid-kpi">
      ${kpi("Cumplimiento SLA resolución", m.sla.resolution_pct, "%")}
      ${kpi("Cumplimiento SLA respuesta", m.sla.response_pct, "%")}
      ${kpi("MTTA", m.mtta_minutes != null ? Math.round(m.mtta_minutes) : null, " min")}
      ${kpi("MTTR", m.mttr_hours, " h")}
      ${kpi("Resolución en 1er contacto", m.first_contact_resolution_pct, "%")}
      ${kpi("Tasa de escalamiento", m.escalation_rate_pct, "%")}
      ${kpi("Backlog abierto", m.backlog.total)}
      ${kpi("Abiertos vencidos", m.backlog.overdue)}
    </div>
    <div class="grid grid-2" style="margin-top:16px">
      <div class="panel"><h2>Volumen semanal</h2><div class="chart-box"><canvas id="c-volume"></canvas></div></div>
      <div class="panel"><h2>Backlog por nivel</h2><div class="chart-box"><canvas id="c-backlog"></canvas></div></div>
      <div class="panel"><h2>Cumplimiento de SLA por prioridad</h2><div class="chart-box"><canvas id="c-priority"></canvas></div></div>
      <div class="panel"><h2>Tickets por categoría</h2><div class="chart-box"><canvas id="c-category"></canvas></div></div>
    </div>
    <div class="grid grid-2">
      <div class="panel"><h2>Por agente (resolvió)</h2><table><thead><tr><th>Agente</th><th>Resueltos</th>
        <th>% SLA</th><th>MTTR (h)</th></tr></thead><tbody>${m.compliance_by_agent.map((r) => `
        <tr><td>${esc(r.key)}</td><td>${r.resolved}</td><td>${r.compliance_pct}%</td><td>${r.mttr_hours}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="panel"><h2>Por nivel de resolución</h2><table><thead><tr><th>Nivel</th><th>Resueltos</th>
        <th>% SLA</th><th>MTTR (h)</th></tr></thead><tbody>${m.compliance_by_level.map((r) => `
        <tr><td>${esc(r.key)}</td><td>${r.resolved}</td><td>${r.compliance_pct}%</td><td>${r.mttr_hours}</td></tr>`).join("")}
      </tbody></table></div>
    </div>`;
  const colors = ["#2f5bea", "#12a150", "#e2a400", "#d92d20", "#7c3aed", "#0891b2", "#db2777", "#65a30d", "#64748b"];
  chart("c-volume", { type: "line", data: {
    labels: m.weekly_volume.map((w) => w.week),
    datasets: [
      { label: "Creados", data: m.weekly_volume.map((w) => w.created), borderColor: colors[0], tension: .3 },
      { label: "Resueltos", data: m.weekly_volume.map((w) => w.resolved), borderColor: colors[1], tension: .3 },
    ] }, options: { maintainAspectRatio: false } });
  chart("c-backlog", { type: "bar", data: {
    labels: Object.keys(m.backlog.by_level),
    datasets: [{ label: "Abiertos", data: Object.values(m.backlog.by_level), backgroundColor: colors[0] }],
  }, options: { maintainAspectRatio: false, plugins: { legend: { display: false } } } });
  chart("c-priority", { type: "bar", data: {
    labels: m.compliance_by_priority.map((r) => r.key),
    datasets: [{ label: "% cumplido", data: m.compliance_by_priority.map((r) => r.compliance_pct),
      backgroundColor: m.compliance_by_priority.map((r) => (r.compliance_pct >= 90 ? colors[1] : r.compliance_pct >= 80 ? colors[2] : colors[3])) }],
  }, options: { maintainAspectRatio: false, scales: { y: { min: 0, max: 100 } }, plugins: { legend: { display: false } } } });
  chart("c-category", { type: "doughnut", data: {
    labels: Object.keys(m.by_category),
    datasets: [{ data: Object.values(m.by_category), backgroundColor: colors }],
  }, options: { maintainAspectRatio: false, plugins: { legend: { position: "right" } } } });
}

// ------------------------------------------------------------------- router
async function loadUser() {
  state.user = await api("/api/auth/me");
  $("#user-name").textContent = `${state.user.full_name} · ${LABELS.role[state.user.role]}`;
  document.querySelectorAll("[data-staff]").forEach((el) => (el.hidden = !isStaff()));
  refreshNotifications();
}

async function refreshNotifications() {
  try {
    const unread = await api("/api/notifications?unread_only=true");
    $("#notif-count").textContent = unread.length ? String(unread.length) : "";
  } catch (err) { /* sin badge */ }
}

function logout() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("token");
  location.hash = "#/login";
}

async function router() {
  cleanup();
  const hash = location.hash || "#/tickets";
  if (!state.token) return renderLogin();
  if (!state.user) {
    try { await loadUser(); } catch (err) { return renderLogin(); }
  }
  $("#topbar").hidden = false;
  const section = hash.split(/[/?]/)[1];
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === section));
  try {
    let m;
    if ((m = hash.match(/^#\/tickets\/(\d+)/))) return await renderTicket(m[1]);
    if ((m = hash.match(/^#\/kb\/(\d+)/))) return await renderArticle(m[1]);
    if (hash.startsWith("#/new")) return renderNew();
    if (hash.startsWith("#/dashboard")) return await renderDashboard();
    if (hash.startsWith("#/notifications")) return await renderNotifications();
    if (hash.startsWith("#/login")) { location.hash = "#/tickets"; return; }
    return await renderTickets();
  } catch (err) {
    $("#view").innerHTML = `<div class="panel">No se pudo cargar la vista: ${esc(err.message)}</div>`;
  }
}

window.addEventListener("hashchange", router);
document.addEventListener("DOMContentLoaded", () => {
  $("#logout").addEventListener("click", logout);
  setInterval(() => state.token && refreshNotifications(), 60000);
  router();
});
