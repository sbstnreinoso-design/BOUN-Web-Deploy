// ── DROPSHIPPING ─────────────────────────────────────────────────────────────
// Inventario del proveedor (Derocha · catálogo Dropi), ventas y liquidación,
// ganadores para traer a la bodega Bogotá y configuración (token, tarifas).
// Usa los helpers globales de app.js: api, esc, cop, isAdmin, openModal, closeModal.

let DS = null;
let DS_TAB = localStorage.getItem("ds_tab") || "inventario";
let DS_VF = "todas";          // filtro de ventas
let DS_POLL = null;

const DS_EST = {
  "entregada":     ["Entregada", "g"],
  "en camino":     ["En camino", "b"],
  "por despachar": ["Por despachar", "a"],
  "cancelada":     ["Cancelada", "m"],
  "devuelta":      ["Devuelta", "r"],
  "no entregada":  ["No entregada", "r"],
};
const dsN = n => Math.round(n || 0).toLocaleString("es-CO");
const dsPct = n => (n == null ? "—" : (Math.round(n * 10) / 10).toLocaleString("es-CO") + " %");
const dsAgo = iso => {
  if (!iso) return "nunca";
  const t = new Date(iso.replace(/([+-]\d\d)(\d\d)$/, "$1:$2")).getTime();
  if (!t) return iso;
  const m = Math.round((Date.now() - t) / 60000);
  if (m < 1) return "hace segundos";
  if (m < 60) return "hace " + m + " min";
  const h = Math.round(m / 60);
  if (h < 48) return "hace " + h + " h";
  return "hace " + Math.round(h / 24) + " días";
};
const dsDay = s => {
  if (!s) return "—";
  const d = new Date(s.slice(0, 10) + "T12:00:00");
  return d.toLocaleDateString("es-CO", { day: "numeric", month: "short" }).replace(".", "") +
    (s.length > 10 ? " · " + s.slice(11, 16) : "");
};
const dsAcct = a => a === "kat" ? `<span class="ds-acct kat">KAT</span>` :
  a === "shop" ? `<span class="ds-acct shop">SHOP</span>` : `<span class="ds-acct boun">BOUN</span>`;

async function refreshDropshipBadge() {
  try {
    const r = await api("/dropship/count");
    const b = document.getElementById("badge-dropship");
    if (b) { b.textContent = r.count > 0 ? r.count : ""; b.style.display = r.count > 0 ? "inline-block" : "none"; }
  } catch (e) {}
}

async function renderDropship(silent) {
  const v = document.getElementById("view");
  if (!silent || !document.getElementById("dsRoot")) {
    v.innerHTML = `<div id="dsRoot"><div class="loading"><span class="spinner"></span> Cargando el inventario del proveedor…</div></div>`;
  }
  try {
    DS = await api("/dropship");
    drawDropship();
    clearTimeout(DS_POLL);
    if (DS.syncing) DS_POLL = setTimeout(() => { if (document.getElementById("dsRoot")) renderDropship(true); }, 4000);
  } catch (e) {
    document.getElementById("dsRoot").innerHTML = `<div class="ds-alert red"><span class="ic">⚠️</span><div>${esc(e.message)}</div></div>`;
  }
}

function dsTab(t) { DS_TAB = t; localStorage.setItem("ds_tab", t); drawDropship(); }

function drawDropship() {
  const r = DS; if (!r) return;
  const k = r.kpis || {}, cfg = r.cfg || {}, sync = r.sync || {};
  const ganadores = (r.productos || []).filter(p => p.ganador);
  const porDesp = (r.ventas || []).filter(x => x.estado === "por despachar").length;
  const tokenOk = r.has_token;
  const live = tokenOk && !sync.stock_error;

  const pubPct = k.stock_total ? Math.round(k.publicable_total / k.stock_total * 100) : 0;
  const pagadoPct = k.total_debe ? Math.min(100, Math.round(k.pagado / k.total_debe * 100)) : 0;
  const margen30 = k.bruto30 ? (k.util30 / k.bruto30 * 100) : null;

  const head = `
    <div class="ds-head">
      <div style="min-width:0">
        <div class="ds-eyebrow"><span class="live ${live ? "" : "off"}"></span>Bodega externa · ${esc(cfg.proveedor || "Proveedor")}</div>
        <div class="ds-title">Dropshipping</div>
        <div class="ds-sub">Productos que están en la bodega del proveedor y que él mismo entrega. Aquí ves su stock real, lo que se publica en MercadoLibre y Shopify (con un colchón del <b>${dsN(cfg.colchon_pct)} %</b>), lo que le debes por cada venta y cuáles conviene traer a la bodega Bogotá.</div>
      </div>
      <div class="ds-actions">
        <button class="ds-btn" id="dsSyncBtn" onclick="dsSync()" ${r.syncing ? "disabled" : ""}>${r.syncing ? '<span class="spinner"></span> Sincronizando…' : "↻ Sincronizar"}</button>
        ${isAdmin() ? `<button class="ds-btn" onclick="dsProductoModal()">＋ Producto</button>
        <button class="ds-btn pri" onclick="dsPagoModal()">＋ Registrar pago</button>
        <button class="ds-btn ghost" onclick="dsConfigModal()" title="Token de Dropi, colchón, tarifas y umbrales">⚙</button>` : ""}
      </div>
    </div>
    <div class="ds-flow">
      <div class="ds-step"><div class="n">01</div><div class="t">Se vende en ML / Shopify</div><div class="d">El motor baja el stock publicado y registra la venta.</div></div>
      <div class="ds-step"><div class="n">02</div><div class="t">Etiqueta al proveedor</div><div class="d">Se le envía la etiqueta de ML por WhatsApp.</div></div>
      <div class="ds-step"><div class="n">03</div><div class="t">Él despacha</div><div class="d">Flex: Derocha Express (tarifa por zona) · Agencia: $0.</div></div>
      <div class="ds-step"><div class="n">04</div><div class="t">Liquidación</div><div class="d">Costo del producto + envío Flex, menos los pagos.</div></div>
    </div>`;

  const kpis = `
    <div class="ds-kpis">
      <div class="ds-kpi hero">
        <div class="k">Saldo a pagar · ${esc(cfg.proveedor || "proveedor")}</div>
        <div class="v">${cop(k.saldo)}</div>
        <div class="s">${cop(k.total_debe)} causado · ${cop(k.pagado)} pagado</div>
        <div class="bar"><i style="width:${pagadoPct}%;background:var(--green)"></i><i style="width:${100 - pagadoPct}%;background:var(--amber)"></i></div>
      </div>
      <div class="ds-kpi">
        <div class="k">Stock del proveedor</div>
        <div class="v">${dsN(k.stock_total)} <span style="font-size:13px;color:var(--muted);font-weight:700">u.</span></div>
        <div class="s"><b style="color:var(--green)">${dsN(k.publicable_total)}</b> publicables · ${k.activos} producto(s) activo(s)${k.sin_stock ? ` · <span class="amber">${k.sin_stock} sin stock</span>` : ""}</div>
        <div class="bar"><i style="width:${pubPct}%;background:var(--green)"></i></div>
      </div>
      <div class="ds-kpi">
        <div class="k">Ventas 30 días</div>
        <div class="v">${dsN(k.unid30)} <span style="font-size:13px;color:var(--muted);font-weight:700">u.</span></div>
        <div class="s">${k.ventas30} orden(es) · ${cop(k.bruto30)} vendidos${porDesp ? ` · <span class="amber">${porDesp} por despachar</span>` : ""}</div>
      </div>
      <div class="ds-kpi">
        <div class="k">Utilidad 30 días</div>
        <div class="v" style="color:${k.util30 >= 0 ? "var(--green)" : "#F0567A"}">${cop(k.util30)}</div>
        <div class="s">Margen neto ${dsPct(margen30)} · <b>${ganadores.length}</b> ganador(es)</div>
      </div>
    </div>`;

  let alerts = "";
  if (!tokenOk) alerts += `<div class="ds-alert blue"><span class="ic">🔑</span><div><b>Stock en modo manual.</b> Cuando conectes el token de Dropi (Mis Integraciones → Agregar), el stock del proveedor se va a leer solo cada ${dsN(cfg.sync_min)} min y se va a cargar al motor de stock.${isAdmin() ? ` <a href="#" onclick="dsConfigModal();return false" style="color:var(--blue)">Conectar Dropi →</a>` : ""}</div></div>`;
  else if (sync.stock_error) alerts += `<div class="ds-alert red"><span class="ic">⚠️</span><div><b>No se pudo leer Dropi:</b> ${esc(sync.stock_error)}. Se muestra el último stock guardado.</div></div>`;
  if (k.sin_tarifa) alerts += `<div class="ds-alert"><span class="ic">📍</span><div><b>${k.sin_tarifa} envío(s) Flex</b> van a una zona sin tarifa acordada con el proveedor. No suman al saldo hasta que les pongas el valor (pestaña Ventas → editar).</div></div>`;
  if (sync.ventas_error) alerts += `<div class="ds-alert red"><span class="ic">⚠️</span><div>Lectura de ventas incompleta: ${esc(sync.ventas_error)}.</div></div>`;

  const nVent = (r.ventas || []).filter(x => x.cuenta).length;
  const tabs = `
    <div class="ds-tabs">
      ${[["inventario", "Inventario", (r.productos || []).length],
         ["ventas", "Ventas y liquidación", nVent],
         ["ganadores", "Ganadores", ganadores.length],
         ["tarifas", "Tarifas Flex", (r.tarifas || []).length]]
      .map(([id, t, c]) => `<button class="ds-tab ${DS_TAB === id ? "on" : ""}" onclick="dsTab('${id}')">${t}<span class="c">${c}</span></button>`).join("")}
    </div>`;

  let body = "";
  if (DS_TAB === "ventas") body = dsDrawVentas();
  else if (DS_TAB === "ganadores") body = dsDrawGanadores();
  else if (DS_TAB === "tarifas") body = dsDrawTarifas();
  else body = dsDrawInventario();

  const foot = `<div class="cap" style="font-size:10.5px;color:var(--dim);text-align:right;margin-top:12px">
      Stock: ${tokenOk ? "Dropi · " + dsAgo(sync.stock_ts) : "manual"} · Ventas ML: ${dsAgo(sync.ventas_ts)}${r.syncing ? ' · <span class="spinner" style="width:9px;height:9px;vertical-align:-1px"></span> actualizando' : ""}</div>`;

  document.getElementById("dsRoot").innerHTML = head + kpis + alerts + tabs + body + foot;
  // Etiquetas por celda para la vista móvil (tabla → tarjetas).
  document.querySelectorAll("#dsRoot table.stack").forEach(t => {
    const hs = [...t.querySelectorAll("thead th")].map(th => th.textContent.trim());
    t.querySelectorAll("tbody tr").forEach(tr => [...tr.children].forEach((td, i) => { if (hs[i]) td.setAttribute("data-label", hs[i]); }));
  });
}

// ── Inventario ───────────────────────────────────────────────────────────────
function dsDrawInventario() {
  const prods = (DS.productos || []).slice().sort((a, b) =>
    (a.estado === "migrado") - (b.estado === "migrado") || (b.ventas30 - a.ventas30) || a.sku.localeCompare(b.sku));
  if (!prods.length) return `<div class="ds-card"><div class="ds-empty">Aún no hay productos dropshipping.${isAdmin() ? ` <a href="#" onclick="dsProductoModal();return false" style="color:var(--blue)">Agregar el primero</a>` : ""}</div></div>`;
  const rows = prods.map(p => {
    const st = p.stock_proveedor, pub = p.publicable || 0;
    const tot = st == null ? 0 : st;
    const res = Math.max(0, tot - pub);
    const wPub = tot ? Math.round(pub / tot * 100) : 0;
    const estado = p.estado === "migrado" ? `<span class="ds-pill v">→ Bodega Bogotá</span>` :
      p.estado === "pausado" ? `<span class="ds-pill m">Pausado</span>` :
      st == null ? `<span class="ds-pill r">Sin stock leído</span>` :
      pub <= 0 ? `<span class="ds-pill r">Agotado</span>` :
      pub <= 5 ? `<span class="ds-pill a">Stock bajo</span>` : `<span class="ds-pill g">Activo</span>`;
    const fuente = st == null ? `<span class="amber">${esc(p.stock_error || "sin lectura")}</span>` :
      `${p.stock_fuente === "dropi" ? "Dropi" : "Manual"} · ${dsAgo(p.stock_ts)}${p.stock_error ? ` · <span class="amber" title="${esc(p.stock_error)}">⚠ error al releer</span>` : ""}`;
    const pubs = (p.ml_items || []).map(it => `<a href="https://articulo.mercadolibre.com.co/${esc(it.item_id.replace(/^MCO/, "MCO-"))}" target="_blank" rel="noopener" style="text-decoration:none">${dsAcct(it.acct)}</a>`).join(" ");
    const cubre = (p.dias_cobertura != null && p.stock_proveedor != null) ? `<div class="ds-meta">${p.dias_cobertura > 99 ? "+99" : p.dias_cobertura} días de cobertura</div>` : "";
    const precioDropi = p.precio_dropi && p.precio_dropi !== p.costo ? `<div class="ds-meta amber" title="Precio actual del proveedor en Dropi">Dropi: ${cop(p.precio_dropi)}</div>` : "";
    return `<tr style="${p.estado === "migrado" ? "opacity:.6" : ""}">
      <td style="min-width:230px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="ds-sku">${esc(p.sku)}</span>${p.ganador ? `<span class="ds-pill g" title="Cumple los 3 criterios">★ Ganador</span>` : ""}</div>
        <div class="ds-name" style="margin-top:4px">${esc(p.nombre)}</div>
        <div class="ds-meta">${p.proveedor_dropi ? esc(p.proveedor_dropi) + " · " : ""}${p.link_dropi ? `<a href="${esc(p.link_dropi)}" target="_blank" rel="noopener">Ver en Dropi ↗</a>` : '<span class="amber">sin link de Dropi</span>'}</div>
      </td>
      <td class="r"><div class="ds-num">${cop(p.costo)}</div>${precioDropi}</td>
      <td class="ds-stock">
        <div class="nums"><span class="big" style="color:${pub > 0 ? "var(--green)" : "#F0567A"}">${dsN(pub)}</span><span class="sm">de ${st == null ? "—" : dsN(st)} · colchón ${dsN(p.colchon_efectivo)} %</span></div>
        <div class="ds-sbar"><i class="pub" style="width:${wPub}%"></i><i class="res" style="width:${tot ? 100 - wPub : 0}%"></i></div>
        <div class="ds-meta">${fuente}</div>
      </td>
      <td class="c">${pubs || '<span class="ds-dim">—</span>'}</td>
      <td class="r"><div class="ds-num">${dsN(p.ventas30)}</div><div class="ds-meta">${dsN(p.ventas7)} en 7 d</div>${cubre}</td>
      <td class="r"><div class="ds-num" style="color:${(p.util30 || 0) >= 0 ? "var(--text)" : "#F0567A"}">${cop(p.util30)}</div><div class="ds-meta">margen ${dsPct(p.margen30)}</div></td>
      <td>${estado}</td>
      <td class="r" style="white-space:nowrap">
        <button class="ds-link" onclick="dsStockModal('${esc(p.sku)}')" title="Cargar stock a mano">✎ Stock</button>
        ${isAdmin() ? `<button class="ds-link" onclick="dsProductoModal('${esc(p.sku)}')" title="Editar producto">⋯</button>` : ""}
      </td></tr>`;
  }).join("");
  const tot = DS.kpis || {};
  return `<div class="ds-card">
    <div class="ds-card-h"><div><div class="t">Inventario del proveedor</div><div class="d">Publicable = stock del proveedor − colchón (mín. ${dsN(DS.cfg.colchon_min)} u.). Es lo que el motor reparte entre ML BOUN, ML KAT y Shopify.</div></div></div>
    <div class="ds-scroll"><table class="ds-table stack" style="min-width:980px">
      <thead><tr><th>Producto</th><th class="r">Costo</th><th>Publicable / stock</th><th class="c">Publicado en</th><th class="r">Ventas 30 d</th><th class="r">Utilidad 30 d</th><th>Estado</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td>${tot.activos} activo(s)</td><td></td><td><span class="ds-num" style="color:var(--green)">${dsN(tot.publicable_total)}</span> <span class="ds-meta" style="display:inline">de ${dsN(tot.stock_total)} u.</span></td><td></td><td class="r">${dsN(tot.unid30)}</td><td class="r">${cop(tot.util30)}</td><td colspan="2"></td></tr></tfoot>
    </table></div></div>`;
}

// ── Ventas y liquidación ────────────────────────────────────────────────────
function dsVentaPasa(x) {
  if (DS_VF === "flex") return x.envio === "flex";
  if (DS_VF === "agencia") return x.envio === "agencia";
  if (DS_VF === "despachar") return x.estado === "por despachar";
  if (DS_VF === "revisar") return x.sin_tarifa || x.excluir || x.envio_override != null;
  return true;
}

function dsDrawVentas() {
  const all = DS.ventas || [];
  const lista = all.filter(dsVentaPasa);
  const n = f => all.filter(x => { const o = DS_VF; DS_VF = f; const r = dsVentaPasa(x); DS_VF = o; return r; }).length;
  const chips = [["todas", "Todas"], ["flex", "Flex"], ["agencia", "Agencia"], ["despachar", "Por despachar"], ["revisar", "Ajustadas / sin tarifa"]]
    .map(([id, t]) => `<button class="ds-chip ${DS_VF === id ? "on" : ""}" onclick="DS_VF='${id}';drawDropship()">${t} · ${n(id)}</button>`).join("");
  const rows = lista.map(x => {
    const [el, ec] = DS_EST[x.estado] || [x.estado || "—", "m"];
    const tach = !x.cuenta;
    const envio = x.envio === "flex" ? `<span class="ds-pill b">Flex</span>` : x.envio === "full" ? `<span class="ds-pill v">Full</span>` : `<span class="ds-pill m">Agencia</span>`;
    return `<tr style="${tach ? "opacity:.5" : ""}">
      <td style="white-space:nowrap"><div style="font-weight:700">${dsDay(x.fecha)}</div><div class="ds-meta">${dsAcct(x.acct)} <a href="https://www.mercadolibre.com.co/ventas/${esc(x.order_id)}/detalle" target="_blank" rel="noopener">#${esc(String(x.order_id).slice(-6))} ↗</a></div></td>
      <td style="min-width:190px"><span class="ds-sku">${esc(x.sku)}</span><div class="ds-meta" style="margin-top:3px">${esc(x.titulo)}</div>${x.nota ? `<div class="ds-meta amber">📝 ${esc(x.nota)}</div>` : ""}</td>
      <td class="c ds-num">${x.qty}</td>
      <td>${envio}<div class="ds-meta">${esc(x.envio === "flex" ? (x.zona || "") + (x.localidad && x.localidad !== x.zona ? " · " + x.localidad : "") : (x.zona || ""))}</div></td>
      <td><span class="ds-pill ${ec}">${esc(el)}</span></td>
      <td class="r"><div class="ds-num">${tach ? `<s>${cop(x.costo_producto + (x.envio_proveedor || 0))}</s>` : cop(x.debe)}</div><div class="ds-meta">${x.qty} × ${cop(x.costo_u)}${x.envio === "flex" ? " + envío " + (x.sin_tarifa ? '<span class="ds-pill r" style="padding:0 6px">sin tarifa</span>' : cop(x.envio_proveedor) + (x.tarifa_no_cobra ? " (pack)" : "") + (x.envio_override != null ? " ✎" : "")) : ""}</div></td>
      <td class="r">${cop(x.neto_ml)}<div class="ds-meta">bruto ${cop(x.bruto)}</div></td>
      <td class="r ds-num" style="color:${x.utilidad >= 0 ? "var(--green)" : "#F0567A"}">${tach ? "—" : cop(x.utilidad)}</td>
      ${isAdmin() ? `<td class="r"><button class="ds-link" onclick="dsVentaModal('${encodeURIComponent(x.key)}')" title="Ajustar">⋯</button></td>` : ""}
    </tr>`;
  }).join("");
  const sum = (f) => lista.filter(x => x.cuenta).reduce((a, x) => a + (f(x) || 0), 0);
  const k = DS.kpis || {};
  const pagos = (DS.pagos || []).slice().sort((a, b) => (b.fecha || "").localeCompare(a.fecha || ""));
  const flexN = all.filter(x => x.cuenta && x.envio === "flex").length;
  const prodTot = all.filter(x => x.cuenta).reduce((a, x) => a + x.costo_producto, 0);
  const envTot = all.filter(x => x.cuenta).reduce((a, x) => a + (x.envio_proveedor || 0), 0);

  const tabla = `<div class="ds-card">
    <div class="ds-card-h"><div><div class="t">Ventas dropshipping</div><div class="d">Leídas de MercadoLibre (BOUN y KAT). Neto ML estimado = precio − comisión − envío cobrado por ML (antes de impuestos).</div></div><div class="ds-chips">${chips}</div></div>
    ${lista.length ? `<div class="ds-scroll"><table class="ds-table stack" style="min-width:860px">
      <thead><tr><th>Fecha</th><th>Producto</th><th class="c">Und</th><th>Envío</th><th>Estado</th><th class="r">Debes al proveedor</th><th class="r">Neto ML</th><th class="r">Utilidad</th>${isAdmin() ? "<th></th>" : ""}</tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td colspan="2">${lista.length} venta(s)</td><td class="c">${sum(x => x.qty)}</td><td colspan="2"></td><td class="r">${cop(sum(x => x.debe))}</td><td class="r">${cop(sum(x => x.neto_ml))}</td><td class="r" style="color:var(--green)">${cop(sum(x => x.utilidad))}</td>${isAdmin() ? "<td></td>" : ""}</tr></tfoot>
    </table></div>` : `<div class="ds-empty">No hay ventas con este filtro.</div>`}
  </div>`;

  const pagosHtml = pagos.length ? pagos.map(p => `<div class="ds-ledger"><div class="ln"><span><b>${dsDay(p.fecha)}</b>${p.nota ? ` · <span class="muted">${esc(p.nota)}</span>` : ""}</span><span style="display:flex;gap:6px;align-items:center"><b class="green">−${cop(p.monto)}</b>${isAdmin() ? `<button class="ds-link" onclick="dsPagoBorrar('${esc(p.id)}')" title="Eliminar pago">✕</button>` : ""}</span></div></div>`).join("")
    : `<div class="ds-empty" style="padding:14px">Aún no hay pagos registrados.</div>`;
  const liq = `<div class="ds-card">
      <div class="ds-card-h"><div class="t">Liquidación · ${esc(DS.cfg.proveedor || "")}</div>${isAdmin() ? `<button class="ds-btn sm pri" onclick="dsPagoModal()">＋ Pago</button>` : ""}</div>
      <div class="ds-ledger">
        <div class="ln"><span>Productos (${all.filter(x => x.cuenta).reduce((a, x) => a + x.qty, 0)} u.)</span><b>${cop(prodTot)}</b></div>
        <div class="ln"><span>Envíos Flex (${flexN})</span><b>${cop(envTot)}</b></div>
        <div class="ln"><span>Envíos por agencia</span><b class="muted">$0</b></div>
        <div class="ln"><span>Pagos realizados</span><b class="green">${k.pagado ? "−" + cop(k.pagado) : "$0"}</b></div>
        <div class="ln tot"><span>Saldo a pagar</span><span>${cop(k.saldo)}</span></div>
      </div>
      <div style="font-size:11px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.3px;margin:16px 0 4px">Pagos</div>
      ${pagosHtml}
      <div class="ds-meta" style="margin-top:10px">Las ventas canceladas antes del despacho no se cobran. Si un envío Flex lleva varias órdenes (pack), el envío se paga una sola vez.</div>
    </div>`;
  return `<div class="ds-liq"><div style="min-width:0">${tabla}</div><div>${liq}</div></div>`;
}

// ── Ganadores ────────────────────────────────────────────────────────────────
function dsDrawGanadores() {
  const cfg = DS.cfg || {};
  const metaU = cfg.ganador_ventas30 || 15, metaM = cfg.ganador_margen_pct || 20;
  const prods = (DS.productos || []).slice().sort((a, b) =>
    (b.ganador - a.ganador) || (b.ventas30 - a.ventas30) || ((b.margen30 || -1) - (a.margen30 || -1)));
  const meter = (val, meta, ok) => {
    const w = Math.max(0, Math.min(100, meta ? val / meta * 100 : 0));
    return `<div class="ds-meter"><i style="width:${w}%;background:${ok ? "var(--green)" : w > 60 ? "var(--amber)" : "var(--dim)"}"></i></div>`;
  };
  const cards = prods.map(p => {
    const c = p.criterios || {};
    const migr = p.estado === "migrado";
    return `<div class="ds-win ${p.ganador ? "yes" : ""}" style="${migr ? "opacity:.65" : ""}">
      <div class="top">
        <div style="min-width:0"><span class="ds-sku">${esc(p.sku)}</span><div class="ds-name" style="margin-top:5px">${esc(p.nombre)}</div></div>
        ${migr ? `<span class="ds-pill v">En Bodega Bogotá</span>` : p.ganador ? `<span class="ds-pill g">★ Traer</span>` : `<span class="ds-pill m">En prueba</span>`}
      </div>
      <div class="ds-crit">
        <div class="row"><span>${c.ventas ? "✅" : "◻️"} Ventas 30 días</span><b>${dsN(p.ventas30)} / ${metaU}</b></div>
        ${meter(p.ventas30, metaU, c.ventas)}
        <div class="row"><span>${c.margen ? "✅" : "◻️"} Margen neto</span><b>${dsPct(p.margen30)} / ${metaM} %</b></div>
        ${meter(p.margen30 || 0, metaM, c.margen)}
        <div class="row"><span>${c.reclamos ? "✅" : "⚠️"} Reclamos por calidad</span><b style="color:${c.reclamos ? "var(--green)" : "#F0567A"}">${dsN(p.reclamos_calidad)}</b></div>
      </div>
      <div class="foot">
        <div class="ds-meta" style="margin:0">Utilidad 30 d <b style="color:var(--text)">${cop(p.util30)}</b> · total ${cop(p.util_total)}</div>
        ${isAdmin() ? (migr ? `<button class="ds-btn sm" onclick="dsReactivar('${esc(p.sku)}')">Volver a dropship</button>`
          : `<button class="ds-btn sm ${p.ganador ? "pri" : ""}" onclick="dsMigrarModal('${esc(p.sku)}')">→ Bodega Bogotá</button>`) : ""}
      </div>
    </div>`;
  }).join("");
  return `<div class="ds-card" style="margin-bottom:14px;padding:13px 16px">
      <div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center;font-size:12px">
        <b>Un producto es ganador cuando cumple los 3:</b>
        <span>📈 ${metaU}+ unidades en 30 días</span><span>💰 margen neto ≥ ${metaM} %</span><span>🛡 0 reclamos por calidad</span>
        <span class="muted" style="margin-left:auto;font-size:11px">Margen neto = (neto ML − costo − envío Flex) ÷ precio de venta</span>
      </div></div>
    <div class="ds-wgrid">${cards || '<div class="ds-empty">Sin productos.</div>'}</div>`;
}

// ── Tarifas ──────────────────────────────────────────────────────────────────
function dsDrawTarifas() {
  const t = DS.tarifas || [];
  const rows = t.map(x => `<tr><td><b>${esc(x.zona)}</b></td><td class="r ds-num">${cop(x.tarifa)}</td><td class="ds-meta">${(x.claves || []).map(esc).join(" · ")}</td></tr>`).join("");
  return `<div class="ds-card">
    <div class="ds-card-h"><div><div class="t">Tarifas Flex · Derocha Express</div><div class="d">Se cobra solo en las ventas Flex, según la zona de entrega. Por agencia no se cobra nada y la recolección de $6.000 no aplica porque los productos ya están en la bodega del proveedor.</div></div>${isAdmin() ? `<button class="ds-btn sm" onclick="dsConfigModal('tarifas')">Editar tarifas</button>` : ""}</div>
    <div class="ds-scroll"><table class="ds-table" style="min-width:480px"><thead><tr><th>Zona</th><th class="r">Tarifa por envío</th><th>Se detecta por</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="ds-alert blue" style="margin-top:14px"><span class="ic">ℹ️</span><div>Condiciones del proveedor: paquetes de máximo 30×30×20 cm y 5 kg · entrega el mismo día hasta las 9:00 p. m. · dos intentos de entrega. Si un envío Flex cae en otra zona, la venta queda marcada <b>"Sin tarifa"</b> hasta que la ajustes.</div></div>
  </div>`;
}

// ── Acciones ─────────────────────────────────────────────────────────────────
async function dsSync() {
  try {
    const b = document.getElementById("dsSyncBtn");
    if (b) { b.disabled = true; b.innerHTML = '<span class="spinner"></span> Sincronizando…'; }
    await api("/dropship/sync", { method: "POST" });
    setTimeout(() => renderDropship(true), 2500);
  } catch (e) { alert(e.message); }
}

function dsStockModal(sku) {
  const p = (DS.productos || []).find(x => x.sku === sku); if (!p) return;
  openModal(`<h3>Stock del proveedor</h3>
    <div class="sub"><span class="ds-sku">${esc(p.sku)}</span> ${esc(p.nombre)}<br>Escribe las unidades que tiene el proveedor ahora (lo que ves en Dropi). La app aplica el colchón del ${dsN(p.colchon_efectivo)} % y publica el resto.</div>
    <div class="ds-form"><div class="full"><label>Unidades en la bodega del proveedor</label>
      <input id="dsStockIn" class="field" type="number" min="0" value="${p.stock_proveedor == null ? "" : p.stock_proveedor}" oninput="dsStockPrev(${Number(p.colchon_efectivo) || 0})"></div>
      <div class="full" id="dsStockPrev"></div></div>
    <div class="ds-mrow"><button class="ds-btn ghost" onclick="closeModal()">Cancelar</button><button class="ds-btn pri" onclick="dsStockSave('${esc(sku)}')">Guardar stock</button></div>`);
  dsStockPrev(Number(p.colchon_efectivo) || 0);
  setTimeout(() => { const i = document.getElementById("dsStockIn"); if (i) i.focus(); }, 50);
}
function dsStockPrev(pct) {
  const st = parseInt(document.getElementById("dsStockIn").value || "0", 10) || 0;
  const res = Math.max(Math.ceil(st * pct / 100), (DS.cfg.colchon_min || 0));
  const pub = Math.max(0, st - res);
  document.getElementById("dsStockPrev").innerHTML = `<div class="ds-alert blue" style="margin-top:2px"><span class="ic">🧮</span><div>Se van a publicar <b style="color:var(--green)">${dsN(pub)}</b> u. y quedan <b>${dsN(Math.min(st, res))}</b> u. de colchón.</div></div>`;
}
async function dsStockSave(sku) {
  const v = parseInt(document.getElementById("dsStockIn").value, 10);
  if (isNaN(v) || v < 0) return alert("Escribe un número válido.");
  try { await api("/dropship/productos/" + encodeURIComponent(sku) + "/stock", { method: "POST", body: JSON.stringify({ stock: v }) }); closeModal(); renderDropship(true); }
  catch (e) { alert(e.message); }
}

function dsItemsRows(items) {
  return (items && items.length ? items : [{ acct: "boun", item_id: "" }]).map(it => `
    <div class="ds-trow" style="grid-template-columns:110px 1fr 28px">
      <select class="field ds-it-acct"><option value="boun" ${it.acct !== "kat" ? "selected" : ""}>ML BOUN</option><option value="kat" ${it.acct === "kat" ? "selected" : ""}>ML KAT</option></select>
      <input class="field ds-it-id" placeholder="MCO1234567890" value="${esc(it.item_id || "")}">
      <button class="ds-link" onclick="this.parentNode.remove()" title="Quitar">✕</button>
    </div>`).join("");
}

function dsProductoModal(sku) {
  const p = sku ? (DS.productos || []).find(x => x.sku === sku) : null;
  const isNew = !p;
  openModal(`<h3>${isNew ? "Nuevo producto dropshipping" : "Editar producto"}</h3>
    <div class="sub">${isNew ? "Se crea en el inventario central con su SKU (DS-…) y queda conectado al motor de stock y al Mapeo." : `<span class="ds-sku">${esc(p.sku)}</span>`}</div>
    <div class="ds-form">
      ${isNew ? `<div><label>SKU</label><input id="dsPSku" class="field" placeholder="DS-ALM-PIERNAS" style="text-transform:uppercase"><div class="hint">Empieza por DS-. Es el mismo SKU que se pone en las publicaciones.</div></div>` : ""}
      <div class="${isNew ? "" : "full"}"><label>Nombre</label><input id="dsPNom" class="field" value="${esc(p ? p.nombre : "")}"></div>
      <div><label>Costo por unidad (lo que cobra el proveedor)</label><input id="dsPCosto" class="field" type="number" min="0" value="${p ? p.costo : ""}"></div>
      <div><label>ID del producto en Dropi</label><input id="dsPDropi" class="field" placeholder="1866621" value="${esc(p && p.dropi_id ? p.dropi_id : "")}"><div class="hint">El número del link: …/product-details/<b>1866621</b>/…</div></div>
      <div><label>Proveedor en Dropi</label><input id="dsPProv" class="field" placeholder="Wopi Bodega" value="${esc(p ? p.proveedor_dropi || "" : "")}"></div>
      <div><label>Colchón propio (%)</label><input id="dsPCol" class="field" type="number" min="0" max="90" placeholder="${dsN(DS.cfg.colchon_pct)} (general)" value="${p && p.colchon_pct != null ? p.colchon_pct : ""}"><div class="hint">Vacío = usa el general.</div></div>
      ${!isNew ? `<div><label>Reclamos por calidad</label><input id="dsPRec" class="field" type="number" min="0" value="${p.reclamos_calidad || 0}"></div>
      <div><label>Estado</label><select id="dsPEst" class="field" ${p.estado === "migrado" ? "disabled" : ""}><option value="activo" ${p.estado === "activo" ? "selected" : ""}>Activo (se publica)</option><option value="pausado" ${p.estado === "pausado" ? "selected" : ""}>Pausado (publica 0)</option>${p.estado === "migrado" ? '<option selected>En Bodega Bogotá</option>' : ""}</select></div>` : ""}
      <div class="full"><label>Publicaciones donde se vende</label><div id="dsPItems">${dsItemsRows(p ? p.ml_items : [])}</div>
        <button class="ds-btn sm ghost" style="margin-top:2px" onclick="document.getElementById('dsPItems').insertAdjacentHTML('beforeend',dsItemsRows([]))">＋ Otra publicación</button></div>
      <div class="full"><label>Notas</label><textarea id="dsPNotas" class="field">${esc(p ? p.notas || "" : "")}</textarea></div>
    </div>
    <div class="ds-mrow">
      ${!isNew ? `<button class="ds-btn ghost" style="margin-right:auto;color:#F0567A" onclick="dsBorrar('${esc(p.sku)}')">Quitar de dropshipping</button>` : ""}
      <button class="ds-btn ghost" onclick="closeModal()">Cancelar</button>
      <button class="ds-btn pri" onclick="dsProductoSave(${isNew ? "null" : `'${esc(p.sku)}'`})">${isNew ? "Crear producto" : "Guardar"}</button></div>`, true);
}

async function dsProductoSave(sku) {
  const g = id => document.getElementById(id);
  const items = [...document.querySelectorAll("#dsPItems .ds-trow")].map(r => ({
    acct: r.querySelector(".ds-it-acct").value, item_id: r.querySelector(".ds-it-id").value.trim()
  })).filter(x => x.item_id);
  const body = {
    nombre: g("dsPNom").value.trim(), costo: parseFloat(g("dsPCosto").value || "0") || 0,
    dropi_id: g("dsPDropi").value.trim() || null, proveedor_dropi: g("dsPProv").value.trim(),
    ml_items: items, notas: g("dsPNotas").value,
  };
  const col = g("dsPCol").value.trim();
  if (!body.nombre) return alert("El nombre es obligatorio.");
  try {
    if (!sku) {
      body.sku = g("dsPSku").value.trim();
      if (!body.sku) return alert("El SKU es obligatorio.");
      if (col !== "") body.colchon_pct = parseFloat(col);
      await api("/dropship/productos", { method: "POST", body: JSON.stringify(body) });
    } else {
      if (col === "") body.quitar_colchon_propio = true; else body.colchon_pct = parseFloat(col);
      if (g("dsPRec")) body.reclamos_calidad = parseInt(g("dsPRec").value || "0", 10);
      if (g("dsPEst") && !g("dsPEst").disabled) body.estado = g("dsPEst").value;
      await api("/dropship/productos/" + encodeURIComponent(sku), { method: "PATCH", body: JSON.stringify(body) });
    }
    closeModal(); renderDropship(true);
  } catch (e) { alert(e.message); }
}

async function dsBorrar(sku) {
  if (!confirm("¿Quitar " + sku + " de dropshipping? Se conserva su historial de ventas, pero deja de leerse su stock.")) return;
  try { await api("/dropship/productos/" + encodeURIComponent(sku), { method: "DELETE" }); closeModal(); renderDropship(true); }
  catch (e) { alert(e.message); }
}

function dsMigrarModal(sku) {
  const p = (DS.productos || []).find(x => x.sku === sku); if (!p) return;
  openModal(`<h3>Pasar a Bodega Bogotá</h3>
    <div class="sub"><span class="ds-sku">${esc(p.sku)}</span> ${esc(p.nombre)}</div>
    <div class="ds-ledger" style="margin-bottom:6px">
      <div class="ln"><span>Ventas 30 días</span><b>${dsN(p.ventas30)} u.</b></div>
      <div class="ln"><span>Margen neto</span><b>${dsPct(p.margen30)}</b></div>
      <div class="ln"><span>Reclamos por calidad</span><b>${dsN(p.reclamos_calidad)}</b></div>
    </div>
    <div class="ds-alert blue"><span class="ic">📦</span><div>El producto <b>conserva su SKU y su historial</b>. Desde ahora el motor de stock deja de leer al proveedor y publica lo que haya en tus bodegas: registra el ingreso de la mercancía en <b>Inventario</b>. Mientras no llegue, se publica 0.</div></div>
    ${p.ganador ? "" : `<div class="ds-alert"><span class="ic">⚠️</span><div>Este producto todavía no cumple los 3 criterios de ganador.</div></div>`}
    <div class="ds-mrow"><button class="ds-btn ghost" onclick="closeModal()">Cancelar</button><button class="ds-btn pri" onclick="dsMigrar('${esc(sku)}')">Confirmar paso a Bodega Bogotá</button></div>`);
}
async function dsMigrar(sku) {
  try { await api("/dropship/productos/" + encodeURIComponent(sku) + "/migrar", { method: "POST" }); closeModal(); renderDropship(true); }
  catch (e) { alert(e.message); }
}
async function dsReactivar(sku) {
  if (!confirm("¿Volver a manejar " + sku + " por dropshipping? El motor vuelve a publicar el stock del proveedor.")) return;
  try { await api("/dropship/productos/" + encodeURIComponent(sku) + "/reactivar", { method: "POST" }); renderDropship(true); }
  catch (e) { alert(e.message); }
}

function dsVentaModal(keyEnc) {
  const key = decodeURIComponent(keyEnc);
  const x = (DS.ventas || []).find(v => v.key === key); if (!x) return;
  openModal(`<h3>Ajustar venta</h3>
    <div class="sub">${dsAcct(x.acct)} #${esc(x.order_id)} · <span class="ds-sku">${esc(x.sku)}</span> · ${x.qty} u. · ${esc(x.envio === "flex" ? "Flex " + (x.zona || "") : "Agencia")}</div>
    <div class="ds-form">
      <div class="full"><label><input type="checkbox" id="dsVEx" ${x.excluir ? "checked" : ""}> No liquidar esta venta (no se le debe al proveedor)</label></div>
      <div class="full"><label>Valor del envío que cobra el proveedor</label><input id="dsVEnv" class="field" type="number" min="0" placeholder="Automático: ${x.envio === "flex" ? (x.tarifa_flex == null ? "sin tarifa" : x.tarifa_flex) : 0}" value="${x.envio_override != null ? x.envio_override : ""}"><div class="hint">Vacío = tarifa automática por zona.</div></div>
      <div class="full"><label>Nota</label><input id="dsVNota" class="field" value="${esc(x.nota || "")}" placeholder="Ej. compra de prueba"></div>
    </div>
    <div class="ds-mrow"><button class="ds-btn ghost" onclick="closeModal()">Cancelar</button><button class="ds-btn pri" onclick="dsVentaSave('${keyEnc}')">Guardar</button></div>`);
}
async function dsVentaSave(keyEnc) {
  const env = document.getElementById("dsVEnv").value.trim();
  const body = { excluir: document.getElementById("dsVEx").checked, nota: document.getElementById("dsVNota").value };
  if (env === "") body.quitar_override = true; else body.envio_override = parseFloat(env);
  try { await api("/dropship/ventas/" + keyEnc, { method: "PATCH", body: JSON.stringify(body) }); closeModal(); renderDropship(true); }
  catch (e) { alert(e.message); }
}

function dsPagoModal() {
  const k = (DS && DS.kpis) || {};
  const hoy = new Date(Date.now() - 5 * 3600e3).toISOString().slice(0, 10);
  openModal(`<h3>Registrar pago al proveedor</h3>
    <div class="sub">Saldo actual con ${esc((DS.cfg || {}).proveedor || "el proveedor")}: <b>${cop(k.saldo)}</b></div>
    <div class="ds-form">
      <div><label>Monto pagado</label><input id="dsPgM" class="field" type="number" min="1" value="${k.saldo > 0 ? k.saldo : ""}"></div>
      <div><label>Fecha</label><input id="dsPgF" class="field" type="date" value="${hoy}"></div>
      <div class="full"><label>Nota</label><input id="dsPgN" class="field" placeholder="Ej. transferencia Bancolombia · ventas hasta 7-nov"></div>
    </div>
    <div class="ds-mrow"><button class="ds-btn ghost" onclick="closeModal()">Cancelar</button><button class="ds-btn pri" onclick="dsPagoSave()">Registrar pago</button></div>`);
}
async function dsPagoSave() {
  const monto = parseFloat(document.getElementById("dsPgM").value || "0");
  if (!(monto > 0)) return alert("Escribe el monto.");
  try {
    await api("/dropship/pagos", { method: "POST", body: JSON.stringify({ monto, fecha: document.getElementById("dsPgF").value, nota: document.getElementById("dsPgN").value }) });
    closeModal(); renderDropship(true);
  } catch (e) { alert(e.message); }
}
async function dsPagoBorrar(id) {
  if (!confirm("¿Eliminar este pago?")) return;
  try { await api("/dropship/pagos/" + encodeURIComponent(id), { method: "DELETE" }); renderDropship(true); }
  catch (e) { alert(e.message); }
}

function dsTarRow(t) {
  return `<div class="ds-trow">
    <input class="field ds-t-z" placeholder="Zona" value="${esc(t.zona || "")}">
    <input class="field ds-t-v" type="number" min="0" placeholder="Tarifa" value="${t.tarifa != null ? t.tarifa : ""}">
    <input class="field ds-t-k" placeholder="claves: usme, soacha…" value="${esc((t.claves || []).join(", "))}">
    <button class="ds-link" onclick="this.parentNode.remove()">✕</button></div>`;
}

function dsConfigModal(foco) {
  const c = DS.cfg || {};
  openModal(`<h3>Configuración de dropshipping</h3>
    <div class="sub">Conexión con Dropi, colchón de seguridad, criterios de ganador y tarifas del proveedor.</div>
    <div class="ds-form">
      <div class="full" style="font-size:11px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.3px">Conexión con Dropi</div>
      <div class="full"><label>Token de integración ${DS.has_token ? '<span class="ds-pill g" style="margin-left:6px">guardado ✓</span>' : ""}</label>
        <input id="dsCTok" class="field" type="password" autocomplete="off" placeholder="${DS.has_token ? "•••••••• (escribe uno nuevo para reemplazarlo)" : "Pega aquí el token de Dropi → Mis Integraciones"}">
        <div class="hint">Se guarda en el servidor y nunca se vuelve a mostrar. ${DS.has_token ? '<a href="#" onclick="dsBorrarToken();return false" style="color:#F0567A">Borrar token</a>' : ""}</div>
        <div id="dsCTest"></div></div>
      <div><label>Leer Dropi cada (min)</label><input id="dsCSync" class="field" type="number" min="5" value="${c.sync_min || 15}"></div>
      <div><label>Ventas desde</label><input id="dsCDesde" class="field" type="date" value="${esc((c.desde || "").slice(0, 10))}"></div>
      <div class="full" style="font-size:11px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.3px;margin-top:6px">Stock publicable</div>
      <div><label>Colchón (% del stock que NO se publica)</label><input id="dsCCol" class="field" type="number" min="0" max="90" value="${c.colchon_pct}"></div>
      <div><label>Mínimo reservado (unidades)</label><input id="dsCMin" class="field" type="number" min="0" value="${c.colchon_min}"></div>
      <div class="full" style="font-size:11px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.3px;margin-top:6px">Ganadores</div>
      <div><label>Unidades en 30 días</label><input id="dsCGu" class="field" type="number" min="1" value="${c.ganador_ventas30}"></div>
      <div><label>Margen neto mínimo (%)</label><input id="dsCGm" class="field" type="number" min="0" value="${c.ganador_margen_pct}"></div>
      <div class="full"><label>Nombre del proveedor</label><input id="dsCProv" class="field" value="${esc(c.proveedor || "")}"></div>
      <div class="full" id="dsCTar" style="font-size:11px;font-weight:800;color:var(--muted);text-transform:uppercase;letter-spacing:.3px;margin-top:6px">Tarifas Flex por zona</div>
      <div class="full"><div class="ds-trow" style="font-size:10.5px;color:var(--muted);font-weight:700"><span>Zona</span><span>Tarifa</span><span>Palabras que la identifican</span><span></span></div>
        <div id="dsCTarRows">${(DS.tarifas || []).map(dsTarRow).join("")}</div>
        <button class="ds-btn sm ghost" onclick="document.getElementById('dsCTarRows').insertAdjacentHTML('beforeend',dsTarRow({}))">＋ Zona</button>
        <div class="hint">Las zonas específicas se revisan antes que Bogotá (p. ej. Usme tiene tarifa propia aunque es de Bogotá).</div></div>
    </div>
    <div class="ds-mrow">
      ${DS.has_token ? `<button class="ds-btn ghost" style="margin-right:auto" onclick="dsProbarDropi()">Probar conexión</button>` : ""}
      <button class="ds-btn ghost" onclick="closeModal()">Cancelar</button>
      <button class="ds-btn pri" onclick="dsConfigSave()">Guardar</button></div>`, true);
  if (foco === "tarifas") setTimeout(() => { const e = document.getElementById("dsCTar"); if (e) e.scrollIntoView({ block: "start" }); }, 60);
}
async function dsConfigSave() {
  const g = id => document.getElementById(id);
  const tarifas = [...document.querySelectorAll("#dsCTarRows .ds-trow")].map(r => ({
    zona: r.querySelector(".ds-t-z").value.trim(), tarifa: parseFloat(r.querySelector(".ds-t-v").value || "0") || 0,
    claves: r.querySelector(".ds-t-k").value.split(",").map(s => s.trim()).filter(Boolean)
  })).filter(t => t.zona && t.claves.length);
  const body = {
    proveedor: g("dsCProv").value.trim() || undefined,
    colchon_pct: parseFloat(g("dsCCol").value), colchon_min: parseInt(g("dsCMin").value || "0", 10),
    ganador_ventas30: parseInt(g("dsCGu").value || "15", 10), ganador_margen_pct: parseFloat(g("dsCGm").value || "20"),
    sync_min: parseInt(g("dsCSync").value || "15", 10), desde: g("dsCDesde").value || undefined, tarifas,
  };
  const tok = g("dsCTok").value.trim(); if (tok) body.dropi_token = tok;
  try {
    await api("/dropship/config", { method: "POST", body: JSON.stringify(body) });
    closeModal();
    if (tok) await api("/dropship/sync", { method: "POST" });
    renderDropship(true);
  } catch (e) { alert(e.message); }
}
async function dsBorrarToken() {
  if (!confirm("¿Borrar el token de Dropi? El stock queda en modo manual.")) return;
  try { await api("/dropship/config", { method: "POST", body: JSON.stringify({ borrar_token: true }) }); closeModal(); renderDropship(true); }
  catch (e) { alert(e.message); }
}
async function dsProbarDropi() {
  const box = document.getElementById("dsCTest");
  box.innerHTML = `<div class="ds-meta" style="margin-top:6px"><span class="spinner" style="width:10px;height:10px"></span> Probando con Dropi…</div>`;
  try {
    const r = await api("/dropship/probar-dropi", { method: "POST" });
    box.innerHTML = r.ok
      ? `<div class="ds-alert blue" style="margin-top:8px"><span class="ic">✅</span><div>Conectado. <span class="ds-sku">${esc(r.sku)}</span> tiene <b>${dsN(r.stock)}</b> u. en Dropi${r.precio ? " · precio " + cop(r.precio) : ""}.</div></div>`
      : `<div class="ds-alert red" style="margin-top:8px"><span class="ic">⚠️</span><div>${esc(r.error || "No se pudo conectar")}${r.token_info ? `<div class="ds-meta" style="margin-top:4px">Token guardado: ${esc(String(r.token_info.largo))} caracteres · ${r.token_info.aud ? "tipo " + esc(r.token_info.aud) : esc(r.token_info.jwt || "")}</div>` : ""}${(r.intentos||[]).length ? `<details style="margin-top:6px"><summary style="cursor:pointer;opacity:.8">Ver intentos (${r.intentos.length})</summary><pre style="white-space:pre-wrap;font-size:11px;opacity:.85;margin:6px 0 0">${esc(r.intentos.join("\n"))}</pre></details>` : ""}</div></div>`;
  } catch (e) { box.innerHTML = `<div class="ds-alert red"><span class="ic">⚠️</span><div>${esc(e.message)}</div></div>`; }
}
