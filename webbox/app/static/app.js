// WebBox Dashboard — rebuilt single-page UI (vanilla, zero deps).
// Goals: cleaner structure, better state management, first-class support for
// custom commands, improved maintainability and UX.
//
// All paths are relative for Ingress or direct serving.

const API_BASE = "api";

// ----- state (single source of truth) --------------------------------------

const state = {
    webboxes: [],
    selectedId: null,
    selectedDeviceKey: null,
    status: null,
    devices: [],
    parameters: [],
    commands: [],
    parameterFilter: "",
    livePollTimer: null,
    healthTimer: null,
    editingId: null,
};

// Simple reactive update helper — merge partial state and re-render affected parts.
function setState(partial) {
    Object.assign(state, partial);
    // Selective re-renders (cheap enough for this scale)
    if ("webboxes" in partial || "selectedId" in partial) renderWebBoxList();
    if ("status" in partial || "selectedId" in partial) renderOverview();
    if ("devices" in partial || "selectedDeviceKey" in partial) renderDevices();
    if ("commands" in partial) renderCommands();
    if ("parameters" in partial || "parameterFilter" in partial) renderParameters();
}

// ----- DOM helpers ---------------------------------------------------------

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value == null || value === false) continue;
        if (key === "class") node.className = value;
        else if (key === "dataset") Object.assign(node.dataset, value);
        else if (key.startsWith("on") && typeof value === "function") {
            node.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (key === "html") {
            node.innerHTML = value;
        } else {
            node.setAttribute(key, value);
        }
    }
    for (const child of children.flat()) {
        if (child == null || child === false) continue;
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
}

function toast(message, kind = "info", timeout = 4000) {
    const el = h("div", { class: `toast ${kind}` }, message);
    $("#toasts").append(el);
    setTimeout(() => {
        el.style.transition = "opacity 200ms";
        el.style.opacity = "0";
        setTimeout(() => el.remove(), 220);
    }, timeout);
}

// ----- API -----------------------------------------------------------------

async function api(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    if (resp.status === 204) return null;
    let body = null;
    try { body = await resp.json(); } catch { body = null; }
    if (!resp.ok) {
        const detail = (body && body.detail) || resp.statusText;
        throw new Error(detail);
    }
    return body;
}

// ----- rendering: sidebar --------------------------------------------------

function renderWebBoxList() {
    const list = $("#webbox-list");
    list.replaceChildren();
    if (state.webboxes.length === 0) {
        list.append(h("p", { class: "muted", style: "padding: 12px; font-size: 13px;" },
            "No WebBoxes yet. Click “Add WebBox” to start."));
        return;
    }
    for (const wb of state.webboxes) {
        const status = wb._status ?? "unknown";
        list.append(h("div", {
            class: `webbox-item ${state.selectedId === wb.id ? "active" : ""}`,
            onclick: () => selectWebBox(wb.id),
        },
            h("span", { class: `status-dot ${status}` }),
            h("div", { class: "meta" },
                h("div", { class: "name" }, wb.name),
                h("div", { class: "host" }, wb.host)
            )
        ));
    }
}

// ----- rendering: view -----------------------------------------------------

function renderOverview() {
    const empty = $("#empty-state");
    const view = $("#webbox-view");
    const wb = currentWebBox();

    if (!wb) {
        empty.classList.remove("hidden");
        view.classList.add("hidden");
        return;
    }
    empty.classList.add("hidden");
    view.classList.remove("hidden");

    $("#wb-title").textContent = wb.name;
    const passwordBadges = [];
    if (wb.has_password) passwordBadges.push("user password ✓");
    if (wb.has_installer_password) passwordBadges.push("installer password ✓");
    const badgeStr = passwordBadges.length ? ` · ${passwordBadges.join(" · ")}` : "";
    $("#wb-subtitle").textContent =
        `${wb.host} · ${wb.source === "options" ? "from add-on options" : "user-added"}${badgeStr}`;

    const isOptionEntry = wb.source === "options";
    const deleteBtn = $("#delete-webbox-btn");
    deleteBtn.disabled = isOptionEntry;
    deleteBtn.title = isOptionEntry
        ? "Defined in the add-on options. Remove it from Settings → Add-ons → WebBox Dashboard → Configuration."
        : "";

    const editBtn = $("#edit-webbox-btn");
    editBtn.disabled = isOptionEntry;
    editBtn.title = isOptionEntry
        ? "Defined in the add-on options. Edit it in Settings → Add-ons → WebBox Dashboard → Configuration, then restart the add-on."
        : "";

    const openBtn = $("#open-webbox-btn");
    const hasPublicUrl = Boolean(wb.public_url);
    openBtn.disabled = !hasPublicUrl;
    openBtn.title = hasPublicUrl
        ? "Open the WebBox's native web UI via its Cloudflare Tunnel"
        : "Set a Public URL (Cloudflare Tunnel hostname) on this WebBox to enable this.";

    const cards = $("#overview-cards");
    cards.replaceChildren();

    if (!state.status) {
        cards.append(h("div", { class: "card" },
            h("div", { class: "label" }, "Status"),
            h("div", { class: "value muted" }, "Loading…")));
        return;
    }
    if (!state.status.online) {
        cards.append(h("div", { class: "card" },
            h("div", { class: "label" }, "Status"),
            h("div", { class: "value", style: "color: var(--danger)" }, "Offline"),
            h("div", { class: "muted", style: "font-size: 12px; margin-top: 4px;" }, state.status.error || "Unreachable")));
        return;
    }

    const overview = state.status.overview || {};
    const entries = Object.entries(overview);
    if (entries.length === 0) {
        cards.append(h("div", { class: "card" },
            h("div", { class: "label" }, "Status"),
            h("div", { class: "value", style: "color: var(--success)" }, "Online")));
        return;
    }
    for (const [key, info] of entries) {
        cards.append(h("div", { class: "card" },
            h("div", { class: "label" }, formatLabel(key)),
            h("div", { class: "value" },
                formatValue(info?.value),
                info?.unit ? h("span", { class: "unit" }, info.unit) : null
            )
        ));
    }
}

function renderDevices() {
    const list = $("#device-list");
    list.replaceChildren();
    const devices = state.devices || [];
    $("#device-count").textContent = String(devices.length);

    if (devices.length === 0) {
        list.append(h("p", { class: "muted" }, "No devices reported."));
        return;
    }
    for (const dev of devices) {
        list.append(h("div", {
            class: `device ${state.selectedDeviceKey === dev.key ? "active" : ""}`,
            onclick: () => selectDevice(dev.key),
        },
            h("div", { class: "name" }, dev.name || dev.key || "Unknown"),
            h("div", { class: "key" }, dev.key || "")
        ));
    }
}

function renderDeviceDetail() {
    const detail = $("#device-detail");
    const dev = state.devices.find((d) => d.key === state.selectedDeviceKey);
    if (!dev) {
        detail.classList.add("hidden");
        return;
    }
    detail.classList.remove("hidden");
    $("#device-title").textContent = `${dev.name || dev.key} — ${dev.key}`;

    // Quick command buttons in header for the "app" feel
    renderQuickCommands();
}

function renderQuickCommands() {
    const container = $("#quick-commands");
    if (!container) return;
    container.replaceChildren();

    const wb = currentWebBox();
    if (!state.selectedDeviceKey || !wb || !wb.has_installer_password) return;

    const all = state.commands || [];
    const byName = (n) => all.find((c) => c.name === n);

    // Prominent Start / Stop buttons for the inverter (Operation.Mode)
    // These are the main "start stop button" controls the user requested.
    const startCmd = byName("start") || { name: "start", label: "Start", group: "Inverter" };
    const stopCmd = byName("stop") || { name: "stop", label: "Stop", group: "Inverter" };

    // Special prominent Start/Stop buttons (larger, colored)
    const startBtn = makeCommandButton(startCmd, true);
    startBtn.classList.add("btn-start");
    startBtn.style.fontWeight = "600";
    startBtn.style.minWidth = "70px";

    const stopBtn = makeCommandButton(stopCmd, true);
    stopBtn.classList.add("btn-stop");
    stopBtn.style.fontWeight = "600";
    stopBtn.style.minWidth = "70px";

    container.append(startBtn, stopBtn);

    // Grid Start/Stop as secondary quick actions (using GdManStr or GdOnOff as appropriate)
    const startGrid = byName("start_grid") || byName("on_grid");
    const stopGrid = byName("stop_grid") || byName("off_grid");

    if (startGrid) {
        const btn = makeCommandButton(startGrid, true);
        btn.style.fontSize = "12px";
        container.append(btn);
    }
    if (stopGrid) {
        const btn = makeCommandButton(stopGrid, true);
        btn.style.fontSize = "12px";
        container.append(btn);
    }

    // Add a few more useful custom/built-in commands (generator, self-consumption, etc.)
    const forcedNames = new Set(["start", "stop", startGrid?.name, stopGrid?.name].filter(Boolean));
    let extraCount = 0;
    for (const c of all) {
        if (forcedNames.has(c.name)) continue;
        if (extraCount >= 2) break;
        const btn = makeCommandButton(c, true);
        btn.style.fontSize = "12px";
        container.append(btn);
        extraCount++;
    }
}

function renderLiveData(rows) {
    const grid = $("#live-data");
    grid.replaceChildren();
    if (!rows || rows.length === 0) {
        grid.append(h("p", { class: "muted" }, "No live data channels."));
        return;
    }
    for (const row of rows) {
        grid.append(h("div", { class: "data-row" },
            h("div", { class: "name" }, formatLabel(row.name)),
            h("div", { class: "value" },
                formatValue(row.value),
                row.unit ? h("span", { class: "unit" }, row.unit) : null
            )
        ));
    }
}

function renderParameters() {
    const container = $("#parameter-groups");
    container.replaceChildren();
    const params = filteredParameters();
    $("#param-info").textContent = `${params.length} parameter${params.length === 1 ? "" : "s"}`;

    if (params.length === 0) {
        container.append(h("p", { class: "muted" }, "No parameters match your filter."));
        return;
    }

    const groups = new Map();
    for (const p of params) {
        const g = p.group || "Other";
        if (!groups.has(g)) groups.set(g, []);
        groups.get(g).push(p);
    }

    const order = ["Battery", "Charging", "Discharging", "Inverter", "Grid", "Energy management", "Backup", "Generator", "Other"];
    const sortedGroups = [...groups.entries()].sort(([a], [b]) => {
        const ia = order.indexOf(a); const ib = order.indexOf(b);
        if (ia === -1 && ib === -1) return a.localeCompare(b);
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
    });

    for (const [group, rows] of sortedGroups) {
        const groupEl = h("div", { class: "parameter-group" }, h("h4", {}, group));
        for (const param of rows) {
            groupEl.append(parameterRow(param));
        }
        container.append(groupEl);
    }
}

function parameterRow(param) {
    const writable = param.writable !== false;
    const original = param.value;
    const wb = currentWebBox();
    const canWrite = writable && wb && wb.has_installer_password;

    const control = buildControl(param);
    control.disabled = !canWrite;

    const saveBtn = h("button", {
        class: "btn btn-primary save-btn",
        onclick: () => saveParameter(param, control, row),
    }, "Save");

    const row = h("div", { class: "parameter-row" },
        h("div", { class: "meta" },
            h("div", { class: "label-row" },
                h("span", { class: "label" }, param.label || param.name),
                h("span", { class: "key" }, param.key || param.name),
                h("span", { class: "badges" },
                    param.unit ? h("span", { class: "badge-pill" }, param.unit) : null,
                    !writable ? h("span", { class: "badge-pill" }, "read-only") : null,
                    canWrite ? null : (writable ? h("span", { class: "badge-pill", title: "Installer password required" }, "locked") : null)
                )
            ),
            param.description ? h("div", { class: "description" }, param.description) : null
        ),
        h("div", { class: "control" }, control, saveBtn)
    );

    control.addEventListener("input", () => {
        const dirty = String(getControlValue(control)) !== String(original ?? "");
        row.classList.toggle("dirty", dirty);
    });

    return row;
}

function buildControl(param) {
    if (param.type === "enum" && Array.isArray(param.options) && param.options.length) {
        const select = h("select", {});
        for (const opt of param.options) {
            const optEl = h("option", { value: String(opt.value) }, opt.label);
            if (String(opt.value) === String(param.value)) optEl.selected = true;
            select.append(optEl);
        }
        return select;
    }
    if (param.type === "bool") {
        const select = h("select", {});
        for (const opt of [["true", "On"], ["false", "Off"]]) {
            const optEl = h("option", { value: opt[0] }, opt[1]);
            if (String(opt[0]) === String(param.value)) optEl.selected = true;
            select.append(optEl);
        }
        return select;
    }
    if (param.type === "number" || param.type === "duration") {
        return h("input", {
            type: "number",
            value: param.value ?? "",
            min: param.min ?? "",
            max: param.max ?? "",
            step: param.step ?? "any",
        });
    }
    return h("input", { type: "text", value: param.value ?? "" });
}

function getControlValue(control) {
    if (control.type === "number") return control.value === "" ? null : Number(control.value);
    return control.value;
}

// ----- commands ------------------------------------------------------------

async function executeCommand(cmdName, triggerBtn = null) {
    const wb = currentWebBox();
    if (!wb || !state.selectedDeviceKey) return;

    const btn = triggerBtn || (typeof event !== "undefined" ? event.currentTarget : null);
    if (btn) btn.disabled = true;

    try {
        await api(`/webboxes/${wb.id}/devices/${encodeURIComponent(state.selectedDeviceKey)}/command`, {
            method: "POST",
            body: JSON.stringify({ command: cmdName }),
        });
        toast(`Command "${cmdName}" executed`, "success");

        // Refresh so the UI reflects any state changes immediately
        await Promise.all([loadDeviceData(), loadParameters()]);
    } catch (err) {
        toast(`Command failed: ${err.message}`, "error");
    } finally {
        if (btn) btn.disabled = false;
    }
}

/**
 * Build a nice command button element.
 * Used for both the Commands tab grid and the quick header actions.
 */
function makeCommandButton(cmd, compact = false) {
    const wb = currentWebBox();
    const can = !!(wb && wb.has_installer_password);
    const label = cmd.label || cmd.name;

    const btn = h("button", {
        class: compact ? "btn btn-ghost cmd-quick" : "btn btn-command",
        disabled: !can,
        title: cmd.description || label,
        onclick: (e) => executeCommand(cmd.name, e.currentTarget),
    });

    // Lightweight icon (emoji fallback — no external assets)
    const iconMap = {
        Inverter: "⚡", Grid: "🔌", Energy: "☀️", Generator: "🔋", Battery: "🔋", Custom: "★"
    };
    const icon = iconMap[cmd.group] || (compact ? "" : "▶");
    btn.innerHTML = icon ? `<span class="cmd-icon">${icon}</span> ${label}` : label;

    return btn;
}

function renderCommands() {
    const container = $("#command-grid");
    if (!container) return;
    container.replaceChildren();

    const cmds = state.commands || [];
    const infoEl = $("#command-info");
    if (infoEl) infoEl.textContent = `${cmds.length} command${cmds.length === 1 ? "" : "s"} (customs included)`;

    if (cmds.length === 0) {
        container.append(h("p", { class: "muted" }, "No commands defined."));
        return;
    }

    const wb = currentWebBox();
    const canExecute = !!(wb && wb.has_installer_password);

    // Group like the parameter editor
    const groups = new Map();
    for (const cmd of cmds) {
        const g = cmd.group || "Other";
        if (!groups.has(g)) groups.set(g, []);
        groups.get(g).push(cmd);
    }

    const order = ["Inverter", "Grid", "Energy", "Generator", "Battery", "Custom", "Other"];
    const sorted = [...groups.entries()].sort(([a], [b]) => {
        const ia = order.indexOf(a); const ib = order.indexOf(b);
        if (ia === -1 && ib === -1) return a.localeCompare(b);
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
    });

    for (const [group, groupCmds] of sorted) {
        const groupEl = h("div", { class: "command-group" },
            h("h5", { class: "command-group-title" }, group)
        );

        const grid = h("div", { class: "command-btn-grid" });

        for (const cmd of groupCmds) {
            grid.append(makeCommandButton(cmd, false));
        }

        groupEl.append(grid);
        container.append(groupEl);
    }

    if (!canExecute) {
        container.append(h("p", { class: "muted small-note" },
            "Installer password required to execute commands on this WebBox."));
    }
}

// ----- actions -------------------------------------------------------------

async function loadWebBoxes() {
    try {
        const items = await api("/webboxes");
        state.webboxes = items;
        renderWebBoxList();
        // Probe statuses in background.
        items.forEach((wb) => probeStatus(wb.id));
    } catch (err) {
        toast(`Failed to load WebBoxes: ${err.message}`, "error");
    }
}

async function probeStatus(id) {
    try {
        const result = await api(`/webboxes/${id}/status`);
        const wb = state.webboxes.find((w) => w.id === id);
        if (!wb) return;
        wb._status = result.online ? "online" : "offline";
        renderWebBoxList();
        if (state.selectedId === id) {
            state.status = result;
            state.devices = result.devices || [];
            renderOverview();
            renderDevices();
        }
    } catch (err) {
        const wb = state.webboxes.find((w) => w.id === id);
        if (wb) {
            wb._status = "offline";
            renderWebBoxList();
        }
    }
}

function currentWebBox() {
    return state.webboxes.find((w) => w.id === state.selectedId) || null;
}

function selectWebBox(id) {
    setState({
        selectedId: id,
        selectedDeviceKey: null,
        status: null,
        devices: [],
        parameters: [],
        commands: [],
    });
    $("#device-detail").classList.add("hidden");
    probeStatus(id);
    schedulePolling();
}

async function selectDevice(deviceKey) {
    setState({ selectedDeviceKey: deviceKey });
    renderDevices();
    renderDeviceDetail();
    activateTab("live");
    await Promise.all([loadDeviceData(), loadParameters(), loadCommands()]);
}

async function loadDeviceData() {
    const wb = currentWebBox();
    if (!wb || !state.selectedDeviceKey) return;
    try {
        const rows = await api(`/webboxes/${wb.id}/devices/${encodeURIComponent(state.selectedDeviceKey)}/data`);
        renderLiveData(rows);
    } catch (err) {
        $("#live-data").replaceChildren(h("p", { class: "muted" }, `Couldn’t read live data: ${err.message}`));
    }
}

async function loadParameters() {
    const wb = currentWebBox();
    if (!wb || !state.selectedDeviceKey) return;
    if (!wb.has_installer_password && !wb.has_password) {
        setState({ parameters: [] });
        $("#param-info").textContent = "Add an installer password on this WebBox to load parameters.";
        return;
    }
    try {
        const rows = await api(`/webboxes/${wb.id}/devices/${encodeURIComponent(state.selectedDeviceKey)}/parameters`);
        setState({ parameters: rows || [] });
    } catch (err) {
        setState({ parameters: [] });
        $("#param-info").textContent = `Couldn’t read parameters: ${err.message}`;
    }
}

async function loadCommands() {
    const wb = currentWebBox();
    if (!wb || !state.selectedDeviceKey) {
        setState({ commands: [] });
        return;
    }
    // Global catalog (now includes any custom_commands from add-on options)
    try {
        const rows = await api(`/commands`);
        setState({ commands: rows || [] });
    } catch (err) {
        setState({ commands: [] });
        const container = $("#command-grid");
        if (container) container.replaceChildren(h("p", { class: "muted" }, `Couldn’t load commands: ${err.message}`));
    }
}

async function saveParameter(param, control, row) {
    const wb = currentWebBox();
    if (!wb) return;
    const value = getControlValue(control);
    const button = $(".save-btn", row);
    button.disabled = true;
    try {
        await api(`/webboxes/${wb.id}/devices/${encodeURIComponent(state.selectedDeviceKey)}/parameters`, {
            method: "PUT",
            body: JSON.stringify({ channel: param.key || param.name, value }),
        });
        toast(`Updated ${param.label || param.name}`, "success");
        row.classList.remove("dirty");

        // Re-fetch authoritative values from the device.
        // This ensures the UI shows the actual (possibly normalized) current value
        // instead of the optimistic one the user typed. Fixes "parameters not changing"
        // perception when the device rejects, rounds, or delays the update.
        await loadParameters();
    } catch (err) {
        toast(`Failed to update: ${err.message}`, "error");
    } finally {
        button.disabled = false;
    }
}

function filteredParameters() {
    const q = state.parameterFilter.trim().toLowerCase();
    if (!q) return state.parameters;
    return state.parameters.filter((p) =>
        (p.label || "").toLowerCase().includes(q) ||
        (p.key || p.name || "").toLowerCase().includes(q) ||
        (p.group || "").toLowerCase().includes(q));
}

function schedulePolling() {
    if (state.livePollTimer) clearInterval(state.livePollTimer);
    if (!state.selectedId) return;
    state.livePollTimer = setInterval(() => {
        probeStatus(state.selectedId);
        if (state.selectedDeviceKey) loadDeviceData();
    }, 15000);
}

function activateTab(name) {
    for (const tab of $$(".tab")) {
        tab.classList.toggle("active", tab.dataset.tab === name);
    }
    $("#tab-live").classList.toggle("hidden", name !== "live");
    $("#tab-parameters").classList.toggle("hidden", name !== "parameters");
    const cmdPane = $("#tab-commands");
    if (cmdPane) {
        cmdPane.classList.toggle("hidden", name !== "commands");
        if (name === "commands" && state.commands.length === 0 && state.selectedDeviceKey) {
            loadCommands(); // lazy load if needed
        }
    }
    if (name === "live" || name === "parameters") {
        // re-render quick commands when leaving commands tab
        renderQuickCommands();
    }
}



// ----- formatting ----------------------------------------------------------

function formatLabel(raw) {
    if (!raw) return "";
    return String(raw)
        .replace(/[._-]+/g, " ")
        .replace(/([a-z])([A-Z])/g, "$1 $2")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/^./, (c) => c.toUpperCase());
}

function formatValue(value) {
    if (value == null) return "—";
    if (typeof value === "number") {
        if (Number.isInteger(value)) return value.toLocaleString();
        return Number(value.toFixed(3)).toLocaleString();
    }
    if (typeof value === "boolean") return value ? "On" : "Off";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
}

// ----- modal plumbing ------------------------------------------------------

function openModal(id, { reset = true } = {}) {
    const modal = document.getElementById(id);
    if (!modal) return;
    if (reset) {
        const form = modal.querySelector("form");
        if (form) form.reset();
    }
    modal.classList.remove("hidden");
}

function closeModal(id) {
    document.getElementById(id)?.classList.add("hidden");
}

document.addEventListener("click", (event) => {
    const t = event.target;
    if (t.matches("[data-close-modal]")) {
        closeModal(t.dataset.closeModal);
    }
    if (t.classList.contains("modal")) {
        t.classList.add("hidden");
    }
});

// Close modals on Escape (better UX)
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        const openModals = $$(".modal:not(.hidden)");
        if (openModals.length) closeModal(openModals[openModals.length - 1].id);
    }
});

// ----- event wiring (improved) ---------------------------------------------

let searchDebounce = null;

function wireEvents() {
    const search = $("#param-search");
    if (search) {
        search.addEventListener("input", (e) => {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => {
                setState({ parameterFilter: e.target.value });
            }, 120);
        });
    }
    $("#add-webbox-btn").addEventListener("click", () => {
        setState({ editingId: null });
        $("#webbox-modal-title").textContent = "Add WebBox";
        const form = $("#webbox-form");
        form.reset();
        form.elements.password.placeholder = "";
        form.elements.installer_password.placeholder = "";
        openModal("webbox-modal", { reset: false });
    });

    $("#edit-webbox-btn").addEventListener("click", () => {
        const wb = currentWebBox();
        if (!wb) return;
        setState({ editingId: wb.id });
        $("#webbox-modal-title").textContent = "Edit WebBox";
        const form = $("#webbox-form");
        form.reset();
        form.elements.name.value = wb.name || "";
        form.elements.host.value = wb.host || "";
        form.elements.public_url.value = wb.public_url || "";
        form.elements.poll_interval.value = wb.poll_interval || 30;
        // Stored passwords are intentionally not sent back to the browser.
        // Surface that with a placeholder so users know blank = keep current.
        form.elements.password.placeholder =
            wb.has_password ? "(saved — leave blank to keep)" : "";
        form.elements.installer_password.placeholder =
            wb.has_installer_password ? "(saved — leave blank to keep)" : "";
        openModal("webbox-modal", { reset: false });
    });

    $("#delete-webbox-btn").addEventListener("click", async () => {
        const wb = currentWebBox();
        if (!wb) return;
        if (!confirm(`Delete WebBox "${wb.name}"?`)) return;
        try {
            await api(`/webboxes/${wb.id}`, { method: "DELETE" });
            toast("WebBox removed", "success");
            setState({ selectedId: null });
            await loadWebBoxes();
        } catch (err) {
            toast(`Couldn’t delete: ${err.message}`, "error");
        }
    });

    $("#refresh-btn").addEventListener("click", () => {
        if (!state.selectedId) return;
        probeStatus(state.selectedId);
        if (state.selectedDeviceKey) {
            loadDeviceData();
            loadParameters();
            loadCommands();
        }
    });

    $("#open-webbox-btn").addEventListener("click", () => {
        const wb = currentWebBox();
        if (!wb || !wb.public_url) return;
        window.open(wb.public_url, "_blank", "noopener");
    });

    $("#webbox-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = Object.fromEntries(new FormData(event.target).entries());
        if (data.poll_interval) data.poll_interval = Number(data.poll_interval);
        let savedId = state.editingId;
        // Don't send blank passwords on edit — they'd wipe stored secrets.
        if (state.editingId) {
            if (!data.password) delete data.password;
            if (!data.installer_password) delete data.installer_password;
            try {
                await api(`/webboxes/${state.editingId}`, { method: "PATCH", body: JSON.stringify(data) });
                toast("WebBox updated", "success");
            } catch (err) { toast(`Update failed: ${err.message}`, "error"); return; }
        } else {
            try {
                const created = await api(`/webboxes`, { method: "POST", body: JSON.stringify(data) });
                savedId = created?.id ?? null;
                toast("WebBox added", "success");
            } catch (err) { toast(`Add failed: ${err.message}`, "error"); return; }
        }
        closeModal("webbox-modal");
        await loadWebBoxes();
        // Force the main view to re-render against the fresh data so the
        // "installer password ✓" badge appears immediately, even if the
        // WebBox isn't reachable yet.
        if (savedId) setState({ selectedId: savedId });
    });

    $("#scan-btn").addEventListener("click", () => openModal("scan-modal"));

    $("#scan-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const subnet = new FormData(event.target).get("subnet");
        const button = event.target.querySelector("button[type=submit]");
        button.disabled = true;
        button.textContent = "Scanning…";
        const results = $("#scan-results");
        results.replaceChildren();
        results.classList.remove("has-results");
        try {
            const data = await api("/scan", { method: "POST", body: JSON.stringify({ subnet }) });
            results.classList.add("has-results");
            if (!data.found.length) {
                results.append(h("p", { class: "muted", style: "padding: 6px;" }, "No WebBoxes responded."));
            } else {
                for (const ip of data.found) {
                    results.append(h("div", { class: "scan-result-row" },
                        h("span", {}, ip),
                        h("button", {
                            class: "btn btn-primary",
                            style: "padding: 4px 8px; font-size: 12px;",
                            onclick: () => {
                                const form = $("#webbox-form");
                                form.reset();
                                form.elements.host.value = ip;
                                form.elements.name.value = `WebBox @ ${ip}`;
                                setState({ editingId: null });
                                $("#webbox-modal-title").textContent = "Add WebBox";
                                closeModal("scan-modal");
                                openModal("webbox-modal", { reset: false });
                            },
                        }, "Add"),
                    ));
                }
            }
        } catch (err) {
            toast(`Scan failed: ${err.message}`, "error");
        } finally {
            button.disabled = false;
            button.textContent = "Start scan";
        }
    });

    for (const tab of $$(".tab")) {
        tab.addEventListener("click", () => activateTab(tab.dataset.tab));
    }

}

async function pollHealth() {
    try {
        const data = await api("/health");
        $("#health-indicator").className = "health-dot online";
        $("#health-label").textContent = `connected · v${data.version}`;
    } catch {
        $("#health-indicator").className = "health-dot offline";
        $("#health-label").textContent = "backend unreachable";
    }
}

async function main() {
    wireEvents();
    await pollHealth();
    if (state.healthTimer) clearInterval(state.healthTimer);
    state.healthTimer = setInterval(pollHealth, 30000);
    await loadWebBoxes();
}

main().catch((err) => {
    console.error(err);
    toast(`Initialisation failed: ${err.message}`, "error");
});
