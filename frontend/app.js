// ── BOUN Web — frontend ──────────────────────────────────────────────────────
let TOKEN = localStorage.getItem("boun_token") || "";
let USER = JSON.parse(localStorage.getItem("boun_user") || "null");

const GCOLORS = {A:"#7FB3E0",B:"#E0A23C",C:"#C58CE6",D:"#5BC8B0",E:"#E68CA8",F:"#A8C46B"};
const isAdmin = () => USER && USER.role === "admin";
const cop = n => "$" + Math.round(n||0).toLocaleString("es-CO");

async function api(path, opts={}){
  opts.headers = Object.assign({"Content-Type":"application/json"}, opts.headers||{});
  if(TOKEN) opts.headers["Authorization"] = "Bearer " + TOKEN;
  const r = await fetch("/api"+path, opts);
  if(r.status===401){
    // Un 401 en el login = credenciales incorrectas, NO sesión expirada.
    // Mostramos el mensaje real del servidor sin cerrar la sesión local.
    if(opts.noAuthRedirect){
      const j = await r.json().catch(()=>({}));
      throw new Error(j.detail || "Usuario o contraseña incorrectos.");
    }
    logoutLocal(); throw new Error("Sesión expirada");
  }
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.detail || "Error");
  return j;
}

// ── Auth ──────────────────────────────────────────────────────────────────
async function doLogin(){
  const u=document.getElementById("lu").value, p=document.getElementById("lp").value;
  const err=document.getElementById("loginErr"); err.textContent="";
  try{
    const r=await api("/login",{method:"POST",noAuthRedirect:true,body:JSON.stringify({username:u,password:p})});
    TOKEN=r.token; USER=r.user;
    localStorage.setItem("boun_token",TOKEN);
    localStorage.setItem("boun_user",JSON.stringify(USER));
    showApp();
  }catch(e){ err.textContent = e.message; }
}
function logoutLocal(){
  TOKEN=""; USER=null; localStorage.removeItem("boun_token"); localStorage.removeItem("boun_user");
  document.getElementById("app").classList.remove("active");
  // Si el admin tiene la llave de auto-login (p.ej. sesión expiró tras un
  // redeploy), reingresa solo en vez de mostrar el login.
  if(localStorage.getItem("boun_admin_k")){ boot(); return; }
  document.getElementById("login").style.display="flex";
}
async function doLogout(){
  try{await api("/logout",{method:"POST"});}catch(e){}
  localStorage.removeItem("boun_admin_k");   // cierre real: olvida la llave admin
  logoutLocal();
}

document.addEventListener("keydown",e=>{ if(e.key==="Enter" && document.getElementById("login").style.display!=="none") doLogin(); });

// ── Navegación ─────────────────────────────────────────────────────────────
const NAV=[
  ["dashboard","⬛  Dashboard"],
  ["cerebro","🧠  Cerebro"],
  ["mapeo","🔗  Mapeo"],
  ["denuncias","🛡  Denuncias"],
  ["ventas","↗  Ventas"],
  ["maria_jose","💸  María José"],
  ["inventory","▦  Inventario"],
  ["cola","📦  Pendientes de bodega"],
  ["my_products","★  Mis Productos"],
  ["products","▤  Productos para comprar"],
  ["settings","⚙  Configuración"],
];
function showApp(){
  document.getElementById("login").style.display="none";
  document.getElementById("app").classList.add("active");
  document.getElementById("uname").textContent=USER.username;
  document.getElementById("urole").textContent=USER.role==="admin"?"Administrador":"Colaborador";
  let nav=NAV.slice();
  if(USER.role==="admin") nav.push(["collaborators","♟  Colaboradores"]);
  document.getElementById("nav").innerHTML=nav.map(([id,t])=>
    `<a href="#" data-nav="${id}" onclick="go('${id}');return false">${t}<span class="navbadge" id="badge-${id}"></span></a>`).join("");
  go("dashboard");
  refreshColaBadge();
  refreshMapeoBadge();
  refreshDenunciasBadge();
  scanGlobalPoll();
}
// ── Indicador flotante global de escaneo (badge fijo, cualquier sección) ─────
let SCAN_FAB_TIMER=null;
async function scanGlobalPoll(){
  // Sondea el estado del escaneo de reconciliación y muestra/oculta el badge.
  // Lo usa cualquier sección: el escaneo puede haberlo lanzado el usuario o una
  // tarea programada. No usa api() para no forzar logout ante un 401 transitorio.
  try{
    const r=await fetch("/api/sync/scan-status",
      {headers: TOKEN?{"Authorization":"Bearer "+TOKEN}:{}});
    if(r.ok){
      const s=await r.json();
      scanFabRender(s);
      const running = s && s.status==="running";
      clearTimeout(SCAN_FAB_TIMER);
      SCAN_FAB_TIMER=setTimeout(scanGlobalPoll, running?2500:9000);
      return;
    }
  }catch(e){}
  clearTimeout(SCAN_FAB_TIMER);
  SCAN_FAB_TIMER=setTimeout(scanGlobalPoll, 12000);
}
function scanFabRender(s){
  const fab=document.getElementById("scanFab");
  if(!fab) return;
  if(s && s.status==="running"){
    const done=s.done||0, total=s.total||0, pct=total?Math.round(done/total*100):0;
    const verbo = s.mode==="apply" ? "Aplicando stock" : "Escaneando inventario";
    const t=fab.querySelector(".sf-txt"); if(t) t.innerHTML=verbo+" · <b>"+done+"/"+total+"</b> · "+pct+"%";
    const bf=fab.querySelector(".sf-bar-fill"); if(bf) bf.style.width=pct+"%";
    fab.classList.toggle("apply", s.mode==="apply");
    fab.classList.add("show");
  } else {
    fab.classList.remove("show");
  }
}
async function refreshColaBadge(){
  try{
    const r=await api("/cola-bodega/count");
    const b=document.getElementById("badge-cola");
    if(b) b.textContent=r.count>0?r.count:"", b.style.display=r.count>0?"inline-block":"none";
  }catch(e){}
}
async function refreshMapeoBadge(){
  try{
    const r=await api("/mapeo/count");
    const b=document.getElementById("badge-mapeo");
    if(b) b.textContent=r.count>0?r.count:"", b.style.display=r.count>0?"inline-block":"none";
  }catch(e){}
}
async function refreshDenunciasBadge(){
  try{
    const r=await api("/denuncias/count");
    const b=document.getElementById("badge-denuncias");
    if(b) b.textContent=r.count>0?r.count:"", b.style.display=r.count>0?"inline-block":"none";
  }catch(e){}
}


function go(id){
  document.querySelectorAll(".nav a").forEach(a=>a.classList.toggle("active",a.dataset.nav===id));
  if(id==="dashboard") renderDashboard();
  else if(id==="cerebro") renderCerebro();
  else if(id==="mapeo") renderMapeo();
  else if(id==="denuncias") renderDenuncias();
  else if(id==="ventas") renderSales();
  else if(id==="maria_jose") renderMariaJose();
  else if(id==="inventory") renderInventory();
  else if(id==="cola") renderCola();
  else if(id==="my_products") renderMyProducts();
  else if(id==="products") renderProducts();
  else if(id==="settings") renderSettings();
  else if(id==="collaborators") renderCollaborators();
}

// ── Modal ───────────────────────────────────────────────────────────────────
function openModal(html,wide){
  const m=document.getElementById("modal");
  m.className="modal"+(wide?" wide":""); m.innerHTML=html;
  document.getElementById("modalBg").classList.add("open");
}
function closeModal(){ document.getElementById("modalBg").classList.remove("open"); }

// ── INVENTARIO ──────────────────────────────────────────────────────────────
let INV=[];
async function renderInventory(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="row-between"><div>
      <div class="page-title">Inventario</div>
      <div class="page-sub">Productos físicos con su código y publicaciones de MercadoLibre.</div>
    </div><div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn-ghost" onclick="exportInv()">⬇ CSV</button>
      <button class="btn-ghost" onclick="downloadInvXlsx(this)">⬇ Excel</button>
      ${isAdmin()?`<button class="btn-ghost" onclick="uploadInvXlsx()">⬆ Subir Excel</button>`:""}
      <button class="btn-acc" onclick="newProduct()">＋ Nuevo producto</button></div></div>
    <input type="file" id="invXlsxInput" accept=".xlsx" style="display:none" onchange="doUploadInvXlsx(this)">
    <div id="invKpis" class="kpis"></div>
    <div id="invList"><div class="loading"><span class="spinner"></span> Cargando inventario…</div></div>`;
  try{ const cr=await api("/combos"); COMBOS=cr.combos||{}; }catch(e){ COMBOS={}; }
  try{ INV=await api("/inventory"); drawInventory(); }
  catch(e){ document.getElementById("invList").innerHTML=`<div class="red">${e.message}</div>`; }
}

function exportInv(){
  if(!INV.length){ alert("Sin datos de inventario."); return; }
  const cols=[["code","Código"],["name","Producto"],["n_links","Publicaciones"],
    ["cost_product","Costo producto"],["cost_shipping","Costo envío"],["__cost_total","Costo total unit"],
    ["qty_bogota","Bod Bogotá"],["qty_yopal","Bod Yopal"],["qty_full","ML Full"],["qty_transit","En camino"],
    ["__inv_total","Inventario total"],["__costo_inv","Costo inventario"],["avg_net","Gan/u prom"],
    ["__gan_esp","Ganancia esperada"],["avg_price","Precio prom"],["__valor_venta","Valor de venta"],
    ["avg_margin","Margen prom %"],["avg_roas","ROAS prom"],["avg_acos","ACOS prom %"],
    ["sold60_total","Vendidas 60d"],["__sugerido","Sugerido compra"],["created_by","Creado por"]];
  const num=v=>(v==null||v==="")?0:Math.round(+v||0);
  let csv=cols.map(c=>c[1]).join(",")+"\n";
  INV.forEach(p=>{
    const u=prodUnits(p), unit=prodCostUnit(p);
    const sug=Math.max(0,Math.ceil((+p.sold60_total||0)/60*90 - u));
    const calc={ __cost_total:unit, __inv_total:u, __costo_inv:unit*u,
      __gan_esp:(+p.avg_net||0)*u, __valor_venta:(+p.avg_price||0)*u, __sugerido:sug };
    const row=cols.map(([f])=>{
      let v=f.startsWith("__")?calc[f]:p[f];
      if(["avg_margin","avg_acos"].includes(f))v=(+v||0).toFixed(1);
      else if(["avg_roas"].includes(f))v=(+v||0).toFixed(2);
      else if(["code","name","created_by"].includes(f))v=(""+(v==null?"":v)).replace(/"/g,'""');
      else v=num(v);
      return /[",\n]/.test(""+v)?`"${v}"`:v;
    });
    csv+=row.join(",")+"\n";
  });
  // fila de TOTALES de la marca
  let tCost=0,tProf=0,tSale=0;
  INV.forEach(p=>{ const u=prodUnits(p); tCost+=prodCostUnit(p)*u; tProf+=(+p.avg_net||0)*u; tSale+=(+p.avg_price||0)*u; });
  csv+=`"TOTAL MARCA",,,,,,,,,,,${Math.round(tCost)},,${Math.round(tProf)},,${Math.round(tSale)},,,,,,\n`;
  const blob=new Blob(["\ufeff"+csv],{type:"text/csv;charset=utf-8"}), a=document.createElement("a");
  a.href=URL.createObjectURL(blob);
  a.download="BOUN_inventario_"+new Date().toISOString().slice(0,10)+".csv"; a.click();
}
function prodUnits(p){ return (+p.qty_bogota||0)+(+p.qty_yopal||0)+(+p.qty_full||0)+(+p.qty_transit||0); }
function prodCostUnit(p){ return (+p.cost_product||0)+(+p.cost_shipping||0); }

// ── Inventario · Excel (descargar / subir) ──────────────────────────────────
async function downloadInvXlsx(btn){
  const old = btn ? btn.textContent : "";
  if(btn){ btn.textContent="⏳ Generando…"; btn.style.pointerEvents="none"; }
  try{
    const r = await fetch("/api/inventory/export.xlsx",
      { headers: TOKEN ? {"Authorization":"Bearer "+TOKEN} : {} });
    if(!r.ok){
      let m="Error "+r.status; try{ m=(await r.json()).detail||m; }catch(e){}
      throw new Error(m);
    }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "BOUN_inventario_"+new Date().toISOString().slice(0,10)+".xlsx";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(()=>URL.revokeObjectURL(a.href), 4000);
  }catch(e){ alert("No se pudo descargar el Excel: "+e.message); }
  finally{ if(btn){ btn.textContent=old; btn.style.pointerEvents=""; } }
}

function uploadInvXlsx(){
  if(!isAdmin()){ alert("Solo el administrador puede subir el inventario."); return; }
  document.getElementById("invXlsxInput").click();
}

async function doUploadInvXlsx(input){
  const f = input.files && input.files[0];
  input.value = "";                       // permite re-subir el mismo archivo
  if(!f) return;
  if(!confirm("Vas a actualizar el inventario con «"+f.name+"».\n\n"+
    "Se actualizan por código: Producto, costos y bodegas (Bogotá/Yopal/En tránsito). "+
    "Las publicaciones asignadas NO se tocan.\n\n⚠ Las bodegas se REEMPLAZAN con el "+
    "valor del Excel; si el motor descontó ventas después de tu descarga, vuelve a "+
    "descargar antes de subir. ¿Continuar?")) return;
  const list = document.getElementById("invList");
  if(list) list.innerHTML = `<div class="loading"><span class="spinner"></span> Procesando Excel…</div>`;
  try{
    const r = await fetch("/api/inventory/import",
      { method:"POST",
        headers: Object.assign({"Content-Type":"application/octet-stream"}, TOKEN ? {"Authorization":"Bearer "+TOKEN} : {}),
        body: f });
    const j = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(j.detail || ("Error "+r.status));
    INV = await api("/inventory"); drawInventory();
    showImportSummary(j);
  }catch(e){
    if(list) list.innerHTML = `<div class="red">${e.message}</div>`;
    alert("No se pudo subir el Excel: "+e.message);
    try{ INV = await api("/inventory"); drawInventory(); }catch(_){}
  }
}

function showImportSummary(j){
  const upd = j.updated || [];
  const rowsHtml = upd.length ? upd.map(u=>{
    const ch = Object.entries(u.changes||{}).map(([k,v])=>esc(k)+": "+v).join(", ");
    return `<tr><td style="padding:4px 8px"><b>${esc(u.code)}</b></td><td style="padding:4px 8px">${esc(ch)}</td></tr>`;
  }).join("") : `<tr><td colspan="2" style="padding:8px;color:#9a948a">Ningún producto cambió.</td></tr>`;
  const nf = (j.not_found||[]).length;
  const er = (j.errors||[]).length;
  openModal(`<h3>Inventario actualizado</h3>
    <div class="page-sub" style="margin-bottom:10px">
      ${j.n_updated} actualizado${j.n_updated!==1?"s":""} ·
      ${j.unchanged} sin cambios ·
      ${nf} código${nf!==1?"s":""} no encontrado${nf!==1?"s":""} ·
      ${er} error${er!==1?"es":""}.</div>
    <div style="max-height:360px;overflow:auto;border:1px solid #3A3A3D;border-radius:8px">
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#252427;color:#F2ECE0">
          <th style="padding:6px 8px;text-align:left">Código</th>
          <th style="padding:6px 8px;text-align:left">Cambios</th></tr></thead>
        <tbody>${rowsHtml}</tbody></table></div>
    ${nf?`<div class="page-sub" style="margin-top:8px">No encontrados: ${esc((j.not_found||[]).join(", "))}</div>`:""}
    ${er?`<div class="red" style="margin-top:8px">Errores: ${esc((j.errors||[]).map(x=>x.code+" ("+x.error+")").join("; "))}</div>`:""}
    <div style="margin-top:14px;text-align:right"><button class="btn-acc" onclick="closeModal()">Listo</button></div>`);
}

function drawKpis(){
  let tCost=0,tProf=0,tSale=0,roas=[],acos=[],marg=[];
  INV.forEach(p=>{ const u=prodUnits(p);
    tCost+=prodCostUnit(p)*u; tProf+=(+p.avg_net||0)*u; tSale+=(+p.avg_price||0)*u;
    if(+p.avg_roas>0)roas.push(+p.avg_roas); if(+p.avg_acos>0)acos.push(+p.avg_acos);
    if(+p.avg_margin)marg.push(+p.avg_margin);
  });
  const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0;
  const k=[
    ["Costo total inventario",cop(tCost),"amber"],
    ["Ganancia esperada",cop(tProf),"green"],
    ["Valor de venta",cop(tSale),"acc"],
    ["Margen promedio",marg.length?avg(marg).toFixed(1)+"%":"—","green"],
    ["ROAS BOUN",roas.length?avg(roas).toFixed(2)+"x":"—","green"],
    ["ACOS BOUN",acos.length?avg(acos).toFixed(1)+"%":"—","muted"],
  ];
  document.getElementById("invKpis").innerHTML=k.map(([c,vv,cl])=>
    `<div class="kpi"><div class="cap">${c}</div><div class="val ${cl}">${vv}</div></div>`).join("");
}

function drawInventory(){
  drawKpis();
  const el=document.getElementById("invList");
  if(!INV.length){ el.innerHTML=`<div class="loading">Sin productos. Crea el primero con «＋ Nuevo producto».</div>`; return; }
  el.innerHTML=INV.map(p=>invCard(p)).join("");
}

const COMBO_COLOR="#C58CE6";
// Cálculo de un combo a partir de sus componentes: SUMA costos y valores
// (× cantidad de cada componente); el stock es lo armable (mínimo). El margen,
// ROAS y ACOS NO se calculan aquí: salen de las propias publicaciones del combo.
function comboCalc(p){
  const comps=(COMBOS&&COMBOS[p.code])||[];
  let cp=0, cs=0, valU=0, netU=0, armBog=null, armYop=null;
  comps.forEach(c=>{
    const comp=(INV||[]).find(x=>x.code===c.codigo);
    const cant=+c.cant||1;
    if(!comp){ armBog=0; armYop=0; return; }
    cp  += (+comp.cost_product||0)*cant;
    cs  += (+comp.cost_shipping||0)*cant;
    valU+= (+comp.avg_price||0)*cant;
    netU+= (+comp.avg_net||0)*cant;
    // Armables POR bodega (no se mezclan: el combo se arma con piezas juntas).
    const mb=Math.floor((+comp.qty_bogota||0)/cant), my=Math.floor((+comp.qty_yopal||0)/cant);
    armBog = armBog===null?mb:Math.min(armBog,mb);
    armYop = armYop===null?my:Math.min(armYop,my);
  });
  armBog=Math.max(0,armBog||0); armYop=Math.max(0,armYop||0);
  return {cost_product:cp, cost_shipping:cs, unit:cp+cs,
          invTotal:armBog+armYop, armBog, armYop, avg_price:valU, avg_net:netU};
}
function mjOwnerBtn(p){
  const on=p.owner==="MARIA_JOSE";
  let lbl="💸 MJ";
  if(on){
    const q=+p.mj_qty||0, c=Math.round(+p.mj_consumed||0);
    lbl = q>0 ? `💸 MJ ${Math.max(q-c,0)}/${q}` : "💸 MJ ✓ todas";
  }
  return `<button class="btn-ghost" title="${on?"Editar/quitar unidades de María José":"Marcar como producto de María José (entra a su liquidación)"}" style="${on?"color:#C9B8FF;border-color:#7D6BD855":""}" onclick="event.stopPropagation();mjMarkModal(${p.id})">${lbl}</button>`;
}
function mjMarkModal(pid){
  const p=(INV||[]).find(x=>x.id===pid)||{};
  const on=p.owner==="MARIA_JOSE";
  const q=+p.mj_qty||0, c=Math.round(+p.mj_consumed||0);
  const todas = on && q<=0;
  openModal(`<h3>💸 Producto de María José</h3>
    <div class="sub">${esc(p.code||"")} · ${esc(p.name||"")}</div>
    <p style="font-size:12.5px;color:var(--muted);margin:0 0 12px">María vende primero <b>sus</b> unidades; cuando se agotan, las siguientes ventas pasan a ser de BOUN y el producto se desmarca solo. Indica cuántas unidades son de ella.</p>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:10px;cursor:pointer">
      <input type="radio" name="mjmode" value="qty" ${todas?"":"checked"} onchange="document.getElementById('mjQty').disabled=false;document.getElementById('mjQty').focus()"> Un número de unidades:
      <input id="mjQty" type="number" min="1" class="field" style="width:90px;height:34px" value="${q>0?q:""}" placeholder="ej. 10" ${todas?"disabled":""}>
    </label>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:6px;cursor:pointer">
      <input type="radio" name="mjmode" value="todas" ${todas?"checked":""} onchange="document.getElementById('mjQty').disabled=true"> Todas las unidades (sin tope)
    </label>
    ${on&&q>0?`<div class="note" style="margin-top:8px">Llevas <b>${c}</b> vendidas de <b>${q}</b>. Si cambias el número, el conteo se reinicia desde hoy.</div>`:""}
    <div id="mjErr" class="red" style="font-size:12px;margin-top:8px"></div>
    <div style="display:flex;gap:8px;justify-content:space-between;margin-top:16px">
      <div>${on?`<button class="btn-danger" onclick="mjUnmark(${pid})">Quitar de María José</button>`:""}</div>
      <div style="display:flex;gap:8px">
        <button class="btn-ghost" onclick="closeModal()">Cancelar</button>
        <button class="btn-acc" onclick="mjMarkSave(${pid})">Guardar</button>
      </div>
    </div>`);
}
async function mjMarkSave(pid){
  const mode=(document.querySelector('input[name="mjmode"]:checked')||{}).value;
  const err=document.getElementById("mjErr");
  let qty=0;
  if(mode!=="todas"){
    qty=parseInt(document.getElementById("mjQty").value||"0",10);
    if(!qty||qty<1){ err.textContent="Ingresa cuántas unidades son de ella (o elige «Todas»)."; return; }
  }
  const hoy=_isoDay(0);
  try{
    await api("/inventory/"+pid,{method:"PATCH",body:JSON.stringify({
      owner:"MARIA_JOSE", mj_qty:qty, mj_anchor:hoy, mj_consumed:0})});
    closeModal(); renderInventory();
  }catch(e){ err.textContent=e.message; }
}
async function mjUnmark(pid){
  try{ await api("/inventory/"+pid,{method:"PATCH",body:JSON.stringify({owner:"BOUN"})}); closeModal(); renderInventory(); }
  catch(e){ alert(e.message); }
}
function invCard(p){
  const photo=p.thumb?`<img class="inv-photo" src="${bigImg(p.thumb)}">`:`<div class="inv-photo"></div>`;
  const comps=(typeof COMBOS!=="undefined"&&COMBOS&&Array.isArray(COMBOS[p.code])&&COMBOS[p.code].length)?COMBOS[p.code]:null;
  const isCombo=!!comps;
  const cc=isCombo?comboCalc(p):null;
  const u=isCombo?cc.invTotal:prodUnits(p);
  const unit=isCombo?cc.unit:prodCostUnit(p);
  const aprice=isCombo?cc.avg_price:(+p.avg_price||0);
  const anet=isCombo?cc.avg_net:(+p.avg_net||0);
  const sug=Math.max(0,Math.ceil((+p.sold60_total||0)/60*90 - u));
  const cardStyle=isCombo?`style="border-color:${COMBO_COLOR};border-left:4px solid ${COMBO_COLOR}"`:"";
  const chip=isCombo
    ? `<span class="code-chip" style="background:${COMBO_COLOR};color:#0A0A0A" title="Este producto es un combo">🧩 ${esc(p.code)}</span>`
    : `<span class="code-chip">📦 ${esc(p.code)}</span>`;
  const comboLine=isCombo
    ? `<div class="inv-meta" style="color:${COMBO_COLOR};font-weight:700;margin-top:3px">🧩 Combo = ${comps.map(c=>esc(c.codigo)+" ×"+c.cant).join(" + ")} <span class="muted" style="font-weight:400">· armables: <b style="color:${COMBO_COLOR}">${cc.invTotal}</b> (Bogotá ${cc.armBog} + Yopal ${cc.armYop}) — solo se arma con componentes de la misma bodega</span></div>`
    : "";
  // Combo: costo/envío/bodegas BLOQUEADOS (se derivan de los componentes).
  const fCosto = isCombo? fcolRO("Costo prod.","🔒 "+cop(cc.cost_product),"acc")
                        : fcol("Costo prod.",inp(p.id,"cost_product",p.cost_product));
  const fEnvio = isCombo? fcolRO("Envío","🔒 "+cop(cc.cost_shipping),"acc")
                        : fcol("Envío",inp(p.id,"cost_shipping",p.cost_shipping));
  // Bodegas: combo siempre bloqueado (🔒). Para usuarios normales son solo
  // lectura (cargan stock con el botón 📥 Ingreso); solo el admin las edita.
  const adminBod=isAdmin();
  const fBog = isCombo? fcolRO("Bod. Bogotá","🔒","muted")
             : adminBod? fcol("Bod. Bogotá",inp(p.id,"qty_bogota",p.qty_bogota,64))
             : fcolRO("Bod. Bogotá",Math.round(+p.qty_bogota||0));
  const fYop = isCombo? fcolRO("Bod. Yopal","🔒","muted")
             : adminBod? fcol("Bod. Yopal",inp(p.id,"qty_yopal",p.qty_yopal,64))
             : fcolRO("Bod. Yopal",Math.round(+p.qty_yopal||0));
  const fTra = isCombo? fcolRO("En camino","🔒","muted") : fcol("En camino",inp(p.id,"qty_transit",p.qty_transit,64));
  return `<div class="inv-card" data-pid="${p.id}" ${cardStyle}>
    <div class="inv-head">
      <span class="expand" onclick="togglePanel(${p.id})">▸</span>
      ${photo}
      ${chip}
      <div style="flex:1">
        <div class="inv-name">${esc(p.name)} ${p.owner==="MARIA_JOSE"?`<span title="Producto de María José" style="font-size:10px;font-weight:800;color:#C9B8FF;background:rgba(125,107,216,.18);border:1px solid #7D6BD855;padding:1px 7px;border-radius:11px;vertical-align:middle">💸 María José${(+p.mj_qty||0)>0?` · ${Math.max((+p.mj_qty||0)-Math.round(+p.mj_consumed||0),0)}/${+p.mj_qty||0} u`:" · todas"}</span>`:""}</div>
        <div class="inv-meta">${p.n_links} publicación${p.n_links!==1?"es":""} asignada${p.n_links!==1?"s":""} ${chCounts(p.n_by_channel)}${p.created_by?" · creado por "+esc(p.created_by):""}</div>
        ${comboLine}
      </div>
      ${mjOwnerBtn(p)}
      ${isCombo?"":`<button class="btn-ghost" onclick="ingresoDialog(${p.id})" title="Sumar mercancía que llegó a bodega">📥 Ingreso</button>`}
      <button class="btn-ghost" onclick="assignDialog(${p.id})">Asignar publicaciones</button>
      <button class="btn-ghost" onclick="editProduct(${p.id})">✏</button>
      ${isAdmin()?`<button class="btn-danger" onclick="delProduct(${p.id})">✕</button>`:""}
    </div>
    <div class="inv-strip">
      ${fCosto}
      ${fEnvio}
      ${fcolRO("Costo total",cop(unit),unit?"acc":"red")}
      <div class="vsep"></div>
      ${fBog}
      ${fYop}
      ${fcolRO("ML Full",p.qty_full||0)}
      ${fTra}
      ${fcolRO(isCombo?"Armables":"Inv. total",u,u?"acc":"red")}
      <div class="vsep"></div>
      ${fcolRO("Costo inv.",cop(unit*u),"amber")}
      ${fcolRO("Gan. esperada",cop(anet*u),"green")}
      ${fcolRO("Valor venta",cop(aprice*u))}
      ${fcolRO("Margen prom.",(+p.avg_margin)?(+p.avg_margin).toFixed(1)+"%":"—",mgColor(+p.avg_margin))}
      ${fcolRO("ROAS prom.",(+p.avg_roas)?(+p.avg_roas).toFixed(2)+"x":"—",roasColor(+p.avg_roas))}
      ${fcolRO("ACOS prom.",(+p.avg_acos)?(+p.avg_acos).toFixed(1)+"%":"—",acosColor(+p.avg_acos))}
      <div class="vsep"></div>
      ${fcolRO("Vend. 60d",p.sold60_total||0)}
      ${isCombo?fcolRO("Sug. compra","—","muted"):fcolRO("Sug. compra",sug?("+"+sug+" u"):"✓ cubierto",sug?"red":"green")}
    </div>
    <div class="panel" id="panel-${p.id}"></div>
  </div>`;
}
function mgColor(m){ return m>=20?"green":m>=8?"amber":(m?"red":"muted"); }
function roasColor(r){ return r>=3?"green":r>=1?"amber":"muted"; }
function acosColor(a){ return (a>0&&a<=20)?"green":a<=30?"amber":(a>30?"red":"muted"); }
function fcol(cap,inner){ return `<div class="fcol"><span class="cap">${cap}</span>${inner}</div>`; }
function fcolRO(cap,val,cl){ return `<div class="fcol"><span class="cap">${cap}</span><span class="ro ${cl||""}">${val}</span></div>`; }
function inp(pid,field,val,w){ const v=(+val)?Math.round(+val):"";
  return `<input type="text" value="${v}" style="${w?`width:${w}px`:''}" onchange="saveField(${pid},'${field}',this.value)">`; }

async function saveField(pid,field,val){
  const num=parseFloat((val||"").replace(/[^0-9.]/g,""))||0;
  const body={}; body[field]=num;
  const p=INV.find(x=>x.id===pid); if(p) p[field]=num;
  drawKpis();
  // refrescar totales de la tarjeta sin recargar todo
  const card=document.querySelector(`.inv-card[data-pid="${pid}"]`);
  if(card){ const fresh=invCard(p); const tmp=document.createElement("div"); tmp.innerHTML=fresh;
    const wasOpen=document.getElementById("panel-"+pid)?.classList.contains("open");
    card.replaceWith(tmp.firstElementChild);
    if(wasOpen) togglePanel(pid);
  }
  try{ await api("/inventory/"+pid,{method:"PATCH",body:JSON.stringify(body)}); }catch(e){ alert(e.message); }
}

function togglePanel(pid){
  const el=document.getElementById("panel-"+pid); if(!el) return;
  if(el.classList.contains("open")){ el.classList.remove("open"); setArrow(pid,"▸"); return; }
  el.classList.add("open"); setArrow(pid,"▾");
  const p=INV.find(x=>x.id===pid); let links=(p.links||[]).slice();
  links.sort((a,b)=>{ const ca=CH_ORDER.indexOf(a.channel||"mercadolibre"),cb=CH_ORDER.indexOf(b.channel||"mercadolibre");
    if(ca!==cb)return ca-cb;
    const ga=a.share_group||"zzz",gb=b.share_group||"zzz";
    if(ga!==gb)return ga<gb?-1:1; return (+b.ml_sold||0)-(+a.ml_sold||0); });
  const hasG=links.some(l=>l.share_group);
  let html = hasG?`<div class="note">● Las marcadas con el mismo punto comparten stock en ML — se cuentan una sola vez.</div>`:"";
  if(!links.length) html=`<div class="note">Sin publicaciones asignadas.</div>`;
  html += links.map(l=>{
    const c=l.channel||"mercadolibre", m=chMeta(c), isML=c==="mercadolibre";
    const g=l.share_group, gc=g?GCOLORS[g]||"#3FCB82":"transparent";
    let title=(l.ml_title||l.ml_item_id||""); if(title.length>60)title=title.slice(0,60)+"…";
    const bits=[l.ml_item_id];
    if(isML){ if(+l.ml_margin)bits.push(`margen ${(+l.ml_margin).toFixed(1)}%`);
      if(+l.ml_roas)bits.push(`ROAS ${(+l.ml_roas).toFixed(2)}x`); if(+l.ml_acos)bits.push(`ACOS ${(+l.ml_acos).toFixed(1)}%`); }
    const url="https://articulo.mercadolibre.com.co/"+(l.ml_item_id||"").replace("MCO","MCO-");
    const titleHtml=isML
      ? `<a href="${url}" target="_blank" style="text-decoration:none;color:var(--text)" title="${esc(l.ml_title||"")}">${esc(title)}</a>`
      : `<span title="${esc(l.ml_title||"")}">${esc(title)}</span>`;
    return `<div class="pub" style="border-left:3px solid ${m.col}">
      ${chBadge(c)}
      ${g?`<span style="color:${gc};font-weight:700;width:16px">●${g}</span>`:""}
      ${l.ml_thumb?`<img src="${l.ml_thumb}">`:`<div style="width:32px;height:32px"></div>`}
      <div class="ptitle">${titleHtml}
        <div class="pmeta">${bits.join("  ·  ")}</div></div>
      ${(+l.ml_price)?`<span style="font-weight:700">${cop(l.ml_price)}</span>`:""}
      ${l.ml_logistic==="fulfillment"?`<span class="badge badge-full">FULL</span>`:""}
      <span class="muted" style="font-size:10px">${Math.round(+l.ml_qty||0)} disp.${g?" (comp.)":""}</span>
      ${isML?`<span class="green" style="font-size:10px;font-weight:700">${Math.round(+l.ml_sold||0)} vend.</span>`:""}
    </div>`;
  }).join("");
  el.innerHTML=html;
}
function setArrow(pid,a){ const c=document.querySelector(`.inv-card[data-pid="${pid}"] .expand`); if(c)c.textContent=a; }

// crear / editar / borrar
function newProduct(){ productForm(null); }
function editProduct(pid){ productForm(INV.find(x=>x.id===pid)); }
function productForm(p){
  const nextCode=()=>{ let mx=0; INV.forEach(x=>{const m=(x.code||"").match(/(\d+)\s*$/); if(m)mx=Math.max(mx,+m[1]);}); return "SKU"+String(mx+1).padStart(3,"0"); };
  openModal(`<h3>${p?"Editar producto":"Nuevo producto"}</h3>
    <div class="sub">El código identifica el producto físico (ej. SKU001).</div>
    <div id="pfErr" class="err"></div>
    <input id="pfCode" class="field" placeholder="Código" value="${p?esc(p.code):nextCode()}">
    <input id="pfName" class="field" placeholder="Nombre del producto" value="${p?esc(p.name):""}">
    <div style="display:flex;gap:8px">
      <input id="pfCp" class="field" placeholder="Costo producto" value="${p&&+p.cost_product?Math.round(p.cost_product):""}">
      <input id="pfCs" class="field" placeholder="Costo envío" value="${p&&+p.cost_shipping?Math.round(p.cost_shipping):""}">
    </div>
    <button class="btn-primary" onclick="saveProduct(${p?p.id:0})">Guardar</button>`);
}
async function saveProduct(pid){
  const code=val("pfCode"),name=val("pfName"),cp=num("pfCp"),cs=num("pfCs");
  const err=document.getElementById("pfErr"); err.textContent="";
  if(code.length<3||!name){ err.textContent="Código (3+) y nombre requeridos."; return; }
  try{
    if(pid) await api("/inventory/"+pid,{method:"PATCH",body:JSON.stringify({code,name,cost_product:cp,cost_shipping:cs})});
    else await api("/inventory",{method:"POST",body:JSON.stringify({code,name,cost_product:cp,cost_shipping:cs})});
    closeModal(); renderInventory();
  }catch(e){ err.textContent=e.message; }
}
async function delProduct(pid){
  const p=INV.find(x=>x.id===pid);
  if(!confirm(`¿Eliminar "${p.code} · ${p.name}" del inventario? Las publicaciones de ML no se tocan.`)) return;
  try{ await api("/inventory/"+pid,{method:"DELETE"}); renderInventory(); }catch(e){ alert(e.message); }
}

// ── Ingreso de mercancía (SUMA, no reemplaza) ───────────────────────────────
function ingresoDialog(pid){
  const p=INV.find(x=>x.id===pid); if(!p) return;
  const bog=Math.round(+p.qty_bogota||0), yop=Math.round(+p.qty_yopal||0);
  openModal(`<h3>📥 Ingreso de mercancía — ${esc(p.code)}</h3>
    <div class="sub">Suma las unidades que <b>llegaron</b> a la bodega. <b>No reemplaza</b> el total: respeta los descuentos por ventas que el sistema ya aplicó, así no se "revive" stock vendido.</div>
    <div id="ingErr" class="err"></div>
    <div class="set-row"><label>Bodega</label>
      <select id="ingBod" class="field" onchange="ingPreview(${pid})">
        <option value="bogota">Bogotá (actual: ${bog})</option>
        <option value="yopal">Yopal (actual: ${yop})</option>
      </select></div>
    <div class="set-row"><label>Unidades que llegaron</label>
      <input id="ingCant" class="field" type="text" placeholder="Ej. 20" autocomplete="off" oninput="ingPreview(${pid})"></div>
    <div class="set-row"><label>Nota (opcional)</label>
      <input id="ingNota" class="field" placeholder="Ej. compra proveedor, factura 123"></div>
    <div id="ingPrev" class="note" style="font-size:13px;min-height:18px"></div>
    <button class="btn-primary" onclick="saveIngreso(${pid})">Registrar ingreso</button>`);
  ingPreview(pid);
}
function ingPreview(pid){
  const p=INV.find(x=>x.id===pid); if(!p) return;
  const bod=val("ingBod");
  const actual=Math.round(+(bod==="bogota"?p.qty_bogota:p.qty_yopal)||0);
  const cant=parseInt((document.getElementById("ingCant").value||"").replace(/[^0-9]/g,""))||0;
  const el=document.getElementById("ingPrev"); if(!el) return;
  el.innerHTML = cant>0
    ? `Quedará en <b class="acc">${actual+cant}</b> unidades en ${bod==="bogota"?"Bogotá":"Yopal"} <span class="muted">(${actual} actual + ${cant} ingresadas)</span>.`
    : "";
}
async function saveIngreso(pid){
  const bod=val("ingBod");
  const cant=parseInt((document.getElementById("ingCant").value||"").replace(/[^0-9]/g,""))||0;
  const nota=val("ingNota");
  const err=document.getElementById("ingErr"); err.textContent="";
  if(cant<=0){ err.textContent="Ingresa una cantidad mayor a 0."; return; }
  try{
    const r=await api("/inventory/"+pid+"/ingreso",{method:"POST",
      body:JSON.stringify({bodega:bod,cantidad:cant,nota})});
    closeModal(); renderInventory();
  }catch(e){ err.textContent=e.message; }
}

// ── asignar publicaciones (multicanal) ──────────────────────────────────────
// Cada canal se distingue por color: ML ámbar · Falabella azul ·
// Shopify BOUN verde · Shopify KAT rosa.
const CHMETA={
  mercadolibre:{lbl:"MercadoLibre",short:"ML",col:"#E0A23C"},
  falabella:{lbl:"Falabella",short:"Falabella",col:"#7FB3E0"},
  shopify_boun:{lbl:"Shopify BOUN",short:"BOUN",col:"#3FCB82"},
  shopify_kat:{lbl:"Shopify KAT",short:"KAT",col:"#E68CA8"},
};
const CH_ORDER=["mercadolibre","falabella","shopify_boun","shopify_kat"];
function chMeta(c){ return CHMETA[c]||{lbl:c||"—",short:c||"—",col:"var(--muted)"}; }
function chBadge(c){ const m=chMeta(c);
  return `<span class="ch-badge" style="background:${m.col}">${esc(m.short)}</span>`; }
function chCounts(byCh){ if(!byCh)return "";
  const out=CH_ORDER.filter(c=>byCh[c]).map(c=>{ const m=chMeta(c);
    return `<span class="ch-count" style="background:${m.col}" title="${esc(m.lbl)}">${esc(m.short)} ${byCh[c]}</span>`; });
  return out.length?`<span class="ch-counts">${out.join("")}</span>`:""; }

let ASSIGN_ITEMS=[], ASSIGN_SHARE={}, ASSIGN_PID=0, ASSIGN_OK_CH=[],
    ASSIGN_FILTER="all", ASSIGN_CHST={};
function aKey(c,id){ return (c||"mercadolibre")+"|"+id; }
async function assignDialog(pid){
  ASSIGN_PID=pid; ASSIGN_FILTER="all"; const p=INV.find(x=>x.id===pid);
  openModal(`<h3>Asignar publicaciones — ${esc(p.code)}</h3>
    <div class="sub">Marca las publicaciones de cada canal que son este producto físico. Cada canal tiene su color. Las de ML con el mismo «●» comparten stock.</div>
    <div id="achips" class="ch-chips"></div>
    <input id="asearch" class="field" placeholder="Buscar por título o ID…" oninput="filterAssign()">
    <div id="aerr" class="err"></div>
    <div id="alist"><div class="loading"><span class="spinner"></span> Conectando con los canales…</div></div>
    <button class="btn-primary" onclick="saveAssign()">Guardar asignación</button>`,true);
  try{
    const r=await api("/inventory/items");
    if(!r.ok){ document.getElementById("alist").innerHTML=`<div class="red">${r.error||"Ningún canal respondió."}</div>`; return; }
    ASSIGN_ITEMS=r.items||[];
    ASSIGN_CHST=r.channels||{};
    // canales que cargaron OK (para reemplazo selectivo al guardar)
    ASSIGN_OK_CH=Object.keys(ASSIGN_CHST).filter(c=>ASSIGN_CHST[c]&&ASSIGN_CHST[c].ok);
    // vínculos actuales por (canal,id)
    const mine=new Set(), other={};
    (r.links||[]).forEach(l=>{ const k=aKey(l.channel,l.ml_item_id);
      if(l.product_id===pid)mine.add(k); else other[k]=l.product_id; });
    // grupos de stock compartido (solo ML tiene upid/inventory_id)
    const byk={}; ASSIGN_ITEMS.forEach(it=>{ const k=it.upid||it.inventory_id; if(k){(byk[k]=byk[k]||[]).push(it);} });
    ASSIGN_SHARE={}; let li=0; const L="ABCDEFGHIJ";
    Object.values(byk).forEach(g=>{ if(g.length>1){const lt=L[li++%10]; g.forEach(it=>ASSIGN_SHARE[aKey(it.channel,it.item_id)]=lt);} });
    ASSIGN_ITEMS.forEach(it=>{ const k=aKey(it.channel,it.item_id); it._mine=mine.has(k); it._other=other[k]; });
    // orden: canal (ML, Falabella, BOUN, KAT) y luego título
    ASSIGN_ITEMS.sort((a,b)=>{ const ca=CH_ORDER.indexOf(a.channel),cb=CH_ORDER.indexOf(b.channel);
      if(ca!==cb)return ca-cb; return (a.title||"").localeCompare(b.title||""); });
    drawChips(); drawAssign();
  }catch(e){ document.getElementById("alist").innerHTML=`<div class="red">${e.message}</div>`; }
}
function drawChips(){
  const cnt={}; ASSIGN_ITEMS.forEach(it=>cnt[it.channel]=(cnt[it.channel]||0)+1);
  const chips=[`<button class="ch-chip ${ASSIGN_FILTER==="all"?"on":""}" onclick="setAssignFilter('all')">Todos (${ASSIGN_ITEMS.length})</button>`];
  CH_ORDER.forEach(c=>{ const m=chMeta(c), n=cnt[c]||0, st=ASSIGN_CHST[c]||{};
    const down=st.ok===false;
    chips.push(`<button class="ch-chip ${ASSIGN_FILTER===c?"on":""}" onclick="setAssignFilter('${c}')" ${down?'title="Este canal no respondió; sus asignaciones se conservan al guardar."':''}>
      <span class="dot" style="background:${m.col}"></span>${esc(m.lbl)} ${down?"⚠":"("+n+")"}</button>`); });
  document.getElementById("achips").innerHTML=chips.join("");
}
function setAssignFilter(c){ ASSIGN_FILTER=c; drawChips(); drawAssign(val("asearch")); }
function drawAssign(filter=""){
  const f=(filter||"").toLowerCase();
  document.getElementById("alist").innerHTML=ASSIGN_ITEMS.filter(it=>
    (ASSIGN_FILTER==="all"||it.channel===ASSIGN_FILTER) &&
    (!f || (it.title||"").toLowerCase().includes(f) || (it.item_id||"").toLowerCase().includes(f) || (it.sku||"").toLowerCase().includes(f))
  ).map(it=>{
    const k=aKey(it.channel,it.item_id);
    const g=ASSIGN_SHARE[k], gc=g?GCOLORS[g]||"#3FCB82":"";
    const m=chMeta(it.channel);
    const meta=[it.sku||it.item_id]; if(it.inventory!=null)meta.push(Math.round(+it.inventory||0)+" disp.");
    return `<div class="assign-row" style="border-left:3px solid ${m.col}">
      <input type="checkbox" ${it._mine?"checked":""} data-iid="${esc(it.item_id)}" data-ch="${it.channel}" style="width:16px;height:16px">
      ${it.thumbnail?`<img src="${it.thumbnail}">`:`<div style="width:38px;height:38px;background:var(--bg);border-radius:6px"></div>`}
      <div class="t">${esc(it.title||it.item_id)}
        <div class="m">${chBadge(it.channel)} ${esc(meta.join(" · "))}</div></div>
      ${g?`<span style="color:${gc};font-weight:700">●${g}</span>`:""}
      ${it._other?`<span class="amber" style="font-size:10px;border:1px solid var(--amber);border-radius:6px;padding:2px 7px">en otro SKU</span>`:""}
    </div>`;
  }).join("") || `<div class="loading">Sin resultados en este canal.</div>`;
}
function filterAssign(){ drawAssign(val("asearch")); }
async function saveAssign(){
  const sel=[...document.querySelectorAll("#alist input[type=checkbox]:checked")]
    .map(c=>aKey(c.dataset.ch,c.dataset.iid));
  const byKey={}; ASSIGN_ITEMS.forEach(it=>byKey[aKey(it.channel,it.item_id)]=it);
  const items=sel.map(k=>{ const it=byKey[k]; if(!it) return null;
    return [it.item_id,it.title||"",it.thumbnail||"",it.sold_total||0,it.inventory||0,it.logistic_type||"",
            it.price||0,it.net_unit||0,it.margin_pct||0,it.ad_roas||0,it.ad_acos||0,it.sold_60d||0,
            it.inventory_id||"",it.upid||"",it.channel||"mercadolibre"]; }).filter(Boolean);
  // Solo reemplazamos los canales que cargaron OK; los caídos se conservan.
  const channels=ASSIGN_OK_CH.length?ASSIGN_OK_CH:CH_ORDER;
  try{ await api(`/inventory/${ASSIGN_PID}/links`,{method:"POST",body:JSON.stringify({items,channels})});
    closeModal(); renderInventory();
  }catch(e){ document.getElementById("aerr").textContent=e.message; }
}

// ── DASHBOARD ────────────────────────────────────────────────────────────────
async function renderDashboard(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="page-title">Dashboard</div>
    <div class="page-sub">Resumen del catálogo de productos para comprar.</div>
    <div id="dashKpis" class="kpis"><div class="loading"><span class="spinner"></span> Cargando…</div></div>
    <div class="page-title" style="font-size:16px;margin-top:18px">Top productos por viabilidad</div>
    <div id="dashTop"></div>`;
  try{
    const st=await api("/stats"); const pr=await api("/products");
    document.getElementById("dashKpis").innerHTML=[
      ["Productos analizados",st.total||0,"acc","de tu catálogo"],
      ["Score promedio",(st.avg_score||0).toFixed(1)+"/10","blue","viabilidad global"],
      ["Mejor margen",(st.best_margin||0).toFixed(1)+"%","green","producto estrella"],
      ["Margen promedio",(st.avg_margin||0).toFixed(1)+"%","amber","de todo el catálogo"],
    ].map(([c,vv,cl,sub])=>`<div class="kpi"><div class="cap">${c}</div><div class="val ${cl}">${vv}</div><div class="cap">${sub}</div></div>`).join("");
    const top=pr.slice(0,8);
    let html=`<table><thead><tr><th></th><th>Producto</th><th>Categoría</th><th>Score</th><th>Margen</th><th>Precio</th><th>Ganancia</th></tr></thead><tbody>`;
    html+=top.map(p=>{ const sc=+p.viability_score||0,scc=sc>=8?"green":sc>=5?"amber":"red",mg=+p.profit_margin_pct||0,mc=mg>=20?"green":mg>=10?"amber":"red";
      return `<tr><td>${p.image_path&&p.image_path.startsWith("http")?`<img class="th" src="${p.image_path}">`:`<div class="th"></div>`}</td>
        <td>${esc((p.name||"").slice(0,32))}</td><td class="muted">${esc((p.category||"").slice(0,20))}</td>
        <td class="${scc}"><b>${sc.toFixed(1)}</b></td><td class="${mc}">${mg.toFixed(1)}%</td>
        <td>${cop(p.sale_price)}</td><td class="${(+p.net_profit>=0)?'green':'red'}">${cop(p.net_profit)}</td></tr>`;
    }).join("");
    document.getElementById("dashTop").innerHTML=top.length?html+"</tbody></table>":`<div class="loading">Catálogo vacío.</div>`;
  }catch(e){ document.getElementById("dashKpis").innerHTML=`<div class="red">${e.message}</div>`; }
}

// ── VENTAS (MercadoLibre + Falabella + total) ───────────────────────────────
let SALES_DAYS=14, SALES_MODE="days", SALES_FROM="", SALES_TO="";
const _isoDay=d=>new Date(Date.now()-(d||0)*86400000).toISOString().slice(0,10);
const WD=["dom","lun","mar","mié","jue","vie","sáb"];
const WDC=["#E0667A","#9BB4D4","#7FD0A0","#E0C060","#C79BE0","#5FC7C0","#E08A4C"];
const _wd=f=>{const d=new Date(f+"T12:00:00");return isNaN(d)?-1:d.getDay();};
function salesQ(force){
  const q=(SALES_MODE==="range"&&SALES_FROM&&SALES_TO)
    ?`date_from=${SALES_FROM}&date_to=${SALES_TO}`:`days=${SALES_DAYS}`;
  return q+(force?"&force=true":"");
}
function salMode(v){
  if(v==="custom"){ SALES_MODE="range"; if(!SALES_FROM){SALES_FROM=_isoDay(7);SALES_TO=_isoDay(0);} renderSales(); }
  else { SALES_MODE="days"; SALES_DAYS=+v; renderSales(true); }
}
function salToggle(f){
  const r=document.getElementById("sd-"+f), x=document.getElementById("sx-"+f);
  if(!r) return;
  const open=r.style.display==="none";
  r.style.display=open?"table-row":"none";
  if(x) x.textContent=open?"▾":"▸";
}
async function renderSales(force){
  const v=document.getElementById("view");
  const periodo = SALES_MODE==="range" ? `${SALES_FROM} → ${SALES_TO}` : `${SALES_DAYS} días`;
  v.innerHTML=`<div class="row-between">
      <div>
        <div class="page-title">Ventas</div>
        <div class="page-sub">Ventas diarias de MercadoLibre y Falabella, con total combinado.</div>
      </div>
      <div class="filters" style="margin:0;align-items:center">
        <select id="salSel" class="field fmini" onchange="salMode(this.value)">
          <option value="7"${SALES_MODE==="days"&&SALES_DAYS==7?" selected":""}>Últimos 7 días</option>
          <option value="14"${SALES_MODE==="days"&&SALES_DAYS==14?" selected":""}>Últimos 14 días</option>
          <option value="30"${SALES_MODE==="days"&&SALES_DAYS==30?" selected":""}>Últimos 30 días</option>
          <option value="custom"${SALES_MODE==="range"?" selected":""}>Personalizado…</option>
        </select>
        ${SALES_MODE==="range"?`
        <input type="date" class="field fmini" value="${SALES_FROM}" max="${_isoDay(0)}" onchange="SALES_FROM=this.value">
        <span class="muted">→</span>
        <input type="date" class="field fmini" value="${SALES_TO}" max="${_isoDay(0)}" onchange="SALES_TO=this.value">
        <button class="btn-acc" style="height:32px;padding:0 16px;border-radius:8px" onclick="renderSales(true)">Aplicar</button>`
        :`<button class="btn-ghost" onclick="renderSales(true)">↻ Actualizar</button>`}
      </div>
    </div>
    <div id="salKpis" class="kpis"><div class="loading"><span class="spinner"></span> Cargando ventas…</div></div>
    <div id="salNote"></div>
    <div id="salTable"></div>`;
  try{
    const r=await api("/sales?"+salesQ(force));
    const dias=r.dias||[];
    const sum=(arr,src,m)=>arr.reduce((a,d)=>a+(d[src]?d[src][m]:0),0);
    const tIng=sum(dias,"total","ingresos"), mIng=sum(dias,"ml","ingresos"), fIng=sum(dias,"falabella","ingresos"), sIng=sum(dias,"shopify","ingresos");
    const tUni=sum(dias,"total","unidades");
    document.getElementById("salKpis").innerHTML=[
      ["Ingresos totales",cop(tIng),"acc",`${periodo} · ML + Falabella + Shopify`],
      ["MercadoLibre",cop(mIng),"amber",sum(dias,"ml","unidades")+" unidades"],
      ["Falabella",cop(fIng),"blue",sum(dias,"falabella","unidades")+" unidades"],
      ["Shopify",cop(sIng),"green",sum(dias,"shopify","unidades")+" unidades"],
      ["Unidades totales",tUni,"acc",dias.length+" días con datos"],
    ].map(([c,vv,cl,sub])=>`<div class="kpi"><div class="cap">${c}</div><div class="val ${cl}">${vv}</div><div class="cap">${sub}</div></div>`).join("");
    // avisos de conexión
    let notes="";
    if(!r.ml_ok) notes+=`<div class="note red">⚠ MercadoLibre: ${esc(r.ml_error||"sin conexión")}</div>`;
    if(!r.fal_ok){
      if(r.fal_stale) notes+=`<div class="note">⚠ Falabella: su API no responde ahora (503); mostrando la <b>última lectura de hace ${r.fal_as_of} min</b>.</div>`;
      else notes+=`<div class="note red">⚠ Falabella: ${esc(r.fal_error||"sin conexión")}</div>`;
    }
    if(!r.shop_ok) notes+=`<div class="note red">⚠ Shopify: ${esc(r.shop_error||"sin conexión")}.</div>`;
    if(r.cache_age_min>0) notes+=`<div class="note">Datos de hace ${r.cache_age_min} min · se refrescan solos cada 10 min.</div>`;
    document.getElementById("salNote").innerHTML=notes;
    // tabla por día (más reciente arriba)
    if(!dias.length){ document.getElementById("salTable").innerHTML=`<div class="loading">Sin ventas en el periodo.</div>`; return; }
    // valores compactos (como antes); el detalle va en el desplegable
    const cel=(o)=>o&&o.unidades?`${o.unidades} u · <b>${cop(o.ingresos)}</b>`:`<span class="muted">0 u · $0</span>`;
    const rx=v=>v==null?`<span class="muted">—</span>`:v+"x";
    const ax=v=>v==null?`<span class="muted">—</span>`:v+"%";
    const detail=(o,label,cls)=>{
      const top=(o&&o.top&&o.top.length)
        ? o.top.map((t,i)=>`<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
            ${t.img?`<img src="${t.img}" loading="lazy" style="width:34px;height:34px;border-radius:5px;object-fit:cover;background:var(--surf);border:1px solid var(--border)">`:`<span class="th" style="width:34px;height:34px"></span>`}
            <span class="pmeta" style="flex:1">${i+1}. ${esc(t.nombre.slice(0,42))} <b>(${t.unidades})</b></span>
          </div>`).join("")
        : `<div class="pmeta">Sin ventas</div>`;
      return `<div style="flex:1;min-width:250px">
        <div class="${cls}" style="font-weight:700;font-size:12px;margin-bottom:4px">${label}</div>
        <div style="font-size:11px">ROAS <b>${rx(o&&o.roas)}</b> · ACOS <b>${ax(o&&o.acos)}</b></div>
        <div style="margin-top:6px"><div class="cap" style="margin-bottom:2px">Productos vendidos${o&&o.top&&o.top.length?` (${o.top.length})`:""}</div><div style="max-height:260px;overflow-y:auto;padding-right:4px">${top}</div></div>
      </div>`;
    };
    let html=`<table class="sales"><thead><tr>
        <th style="width:18px"></th>
        <th>Fecha</th>
        <th><span class="amber">● MercadoLibre</span></th>
        <th><span class="blue">● Falabella</span></th>
        <th><span class="green">● Shopify</span></th>
        <th>Total del día</th>
      </tr></thead><tbody>`;
    html+=dias.slice().reverse().map(d=>{
      const w=_wd(d.fecha), c=WDC[w]||"var(--muted)";
      const we=(w===0||w===6)?` style="background:rgba(255,255,255,.04)"`:"";
      return `<tr class="srow"${we} onclick="salToggle('${d.fecha}')">
        <td class="expand" id="sx-${d.fecha}">▸</td>
        <td style="border-left:3px solid ${c}"><span style="color:${c};font-weight:700">${WD[w]||""}</span> <b>${esc(d.fecha)}</b></td>
        <td class="amber">${cel(d.ml)}</td>
        <td class="blue">${cel(d.falabella)}</td>
        <td class="green">${cel(d.shopify)}</td>
        <td class="acc"><b>${d.total.unidades} u · ${cop(d.total.ingresos)}</b></td>
      </tr>
      <tr class="sdetail" id="sd-${d.fecha}" style="display:none"><td></td><td colspan="5">
        <div style="display:flex;gap:28px;flex-wrap:wrap;padding:4px 0 8px">
          ${detail(d.ml,"MercadoLibre","amber")}
          ${detail(d.falabella,"Falabella","blue")}
          ${detail(d.shopify,"Shopify","green")}
        </div>
      </td></tr>`;
    }).join("");
    // fila de totales
    html+=`<tr style="border-top:2px solid var(--acc)">
        <td></td>
        <td><b>TOTAL${SALES_MODE==="range"?"":` ${SALES_DAYS}d`}</b></td>
        <td class="amber">${sum(dias,"ml","unidades")} u · <b>${cop(mIng)}</b></td>
        <td class="blue">${sum(dias,"falabella","unidades")} u · <b>${cop(fIng)}</b></td>
        <td class="green">${sum(dias,"shopify","unidades")} u · <b>${cop(sIng)}</b></td>
        <td class="acc"><b>${tUni} u · ${cop(tIng)}</b></td>
      </tr>`;
    document.getElementById("salTable").innerHTML=html+"</tbody></table>";
  }catch(e){ document.getElementById("salKpis").innerHTML=`<div class="red">${esc(e.message)}</div>`; }
}

// ── MARÍA JOSÉ · Liquidación ─────────────────────────────────────────────────
let MJ=null;
const MJ_PLAT={mercadolibre:["MercadoLibre","#E0A23C"],falabella:["Falabella","#7FB3E0"],
  shopify_boun:["Shopify BOUN","#3FCB82"],shopify_kat:["Shopify KAT","#E68CA8"]};
function mjPlatChip(p){ const [lbl,col]=MJ_PLAT[p]||[p,"#9B9A96"];
  return `<span style="display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:11px;border:1px solid ${col}55;background:${col}1A;color:${col};font-size:10.5px;font-weight:700"><span style="width:6px;height:6px;border-radius:50%;background:${col}"></span>${esc(lbl)}</span>`; }
function mjDate(s){ if(!s) return "—"; try{ return new Date(s+"T12:00:00").toLocaleDateString("es-CO",{day:"2-digit",month:"short",year:"2-digit"}); }catch(e){ return s; } }

async function renderMariaJose(force){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="row-between"><div>
      <div class="page-title">💸 María José · Liquidación</div>
      <div class="page-sub">Lo que se le debe a María José por sus productos propios, en tiempo real. Cada venta de sus publicaciones, su plataforma, el precio, los costos reales descontados (comisión, retención, envío y publicidad), el ROAS/ACOS y cuándo libera cada plataforma el dinero. El saldo va sumando y se le restan los abonos que le pagues.</div>
    </div><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
      <button class="btn-acc" onclick="mjAbonoModal()">＋ Registrar abono</button>
      <button class="btn-ghost" onclick="renderMariaJose(true)">↻ Actualizar</button>
    </div></div>
    <div id="mjKpis" class="kpis"><div class="loading"><span class="spinner"></span> Calculando liquidación de María José…</div></div>
    <div id="mjNote"></div>
    <div id="mjBody"></div>`;
  try{
    MJ=await api("/mj"+(force?"?force=1":""));
    drawMJ();
  }catch(e){ document.getElementById("mjKpis").innerHTML=`<div class="red">${esc(e.message)}</div>`; }
}

function drawMJ(){
  const r=MJ; if(!r) return;
  const k=r.kpis||{};
  document.getElementById("mjKpis").innerHTML=`
    <div style="display:flex;gap:12px;flex-wrap:wrap;width:100%">
      <div class="kpi" style="flex:1;min-width:200px;border:1px solid var(--acc);background:linear-gradient(135deg,rgba(125,107,216,.12),transparent)">
        <div class="cap">Saldo a pagar a María José</div>
        <div class="val acc" style="font-size:28px">${cop(k.saldo||0)}</div>
        <div class="cap">Ya liberado y por pagar: <b style="color:var(--green)">${cop(k.saldo_liberado||0)}</b></div>
      </div>
      <div class="kpi" style="flex:1;min-width:150px"><div class="cap">Neto total (le corresponde)</div><div class="val green">${cop(k.neto||0)}</div><div class="cap">${k.ventas||0} ventas · bruto ${cop(k.bruto||0)}</div></div>
      <div class="kpi" style="flex:1;min-width:140px"><div class="cap">Liberado por plataformas</div><div class="val">${cop(k.neto_liberado||0)}</div><div class="cap">Pendiente de liberación: ${cop(k.neto_pendiente||0)}</div></div>
      <div class="kpi" style="flex:1;min-width:140px"><div class="cap">Abonos pagados</div><div class="val amber">${cop(k.abonos||0)}</div><div class="cap">${(r.abonos||[]).length} abono(s)</div></div>
    </div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;width:100%;margin-top:2px">
      <div class="kpi" style="flex:1;min-width:120px"><div class="cap">Comisión plataformas</div><div class="val" style="color:#E08A8A">−${cop(k.comision||0)}</div></div>
      <div class="kpi" style="flex:1;min-width:120px"><div class="cap">Retención fuente</div><div class="val" style="color:#E08A8A">−${cop(k.retencion||0)}</div></div>
      <div class="kpi" style="flex:1;min-width:120px"><div class="cap">Envío / Full</div><div class="val" style="color:#E08A8A">−${cop(k.envio||0)}</div></div>
      <div class="kpi" style="flex:1;min-width:120px"><div class="cap">Publicidad</div><div class="val" style="color:#E08A8A">−${cop(k.publicidad||0)}</div></div>
    </div>`;

  // Avisos
  let notes="";
  if(r.cache_age_min>0) notes+=`<div class="note">Datos de hace ${r.cache_age_min} min · se refrescan solos cada 10 min (o usa ↻ Actualizar).</div>`;
  if(!(r.ventas||[]).length){
    notes+=`<div class="note">Aún no hay ventas atribuidas a María José. Marca sus productos en <b>Inventario</b> (botón «Producto de María José» en cada tarjeta) y vuelve aquí — sus ventas aparecerán solas.</div>`;
  }
  document.getElementById("mjNote").innerHTML=notes;

  // Resumen por plataforma
  const pp=r.por_plataforma||{};
  const platCards=Object.keys(pp).map(p=>{
    const [lbl,col]=MJ_PLAT[p]||[p,"#9B9A96"]; const b=pp[p];
    return `<div class="card" style="flex:1;min-width:150px;padding:12px 14px;border-left:3px solid ${col}">
      <div style="font-size:11px;font-weight:700;color:${col}">${esc(lbl)}</div>
      <div style="font-size:18px;font-weight:800;margin-top:2px">${cop(b.neto)}</div>
      <div class="cap">${b.unidades} u · bruto ${cop(b.bruto)}</div></div>`;
  }).join("");

  const ventas=r.ventas||[];
  const filas=ventas.map(vv=>{
    const foto=vv.thumb?`<img src="${esc(vv.thumb)}" loading="lazy" style="width:42px;height:42px;border-radius:7px;object-fit:cover;background:var(--surf);border:1px solid var(--border)">`
      :`<span style="width:42px;height:42px;border-radius:7px;background:var(--surf);border:1px solid var(--border);display:inline-flex;align-items:center;justify-content:center;font-size:16px">📦</span>`;
    const lib=vv.liberado
      ?`<span style="color:var(--green);font-weight:700">● Liberado</span>`
      :`<span style="color:var(--amber);font-weight:700">○ ${mjDate(vv.release_date)}</span>`;
    const ads=(vv.roas||vv.acos)?`<div class="cap" style="font-size:9.5px">ROAS ${vv.roas?vv.roas+"x":"—"} · ACOS ${vv.acos?vv.acos+"%":"—"}</div>`:"";
    return `<tr>
      <td style="display:flex;align-items:center;gap:9px">${foto}<div><div style="font-weight:600;font-size:12px;line-height:1.25">${esc((vv.nombre||"").slice(0,46))}</div><div class="cap" style="font-size:10px">${esc(vv.codigo||"")} · ${mjDate(vv.fecha_venta)}</div></div></td>
      <td>${mjPlatChip(vv.plataforma)}</td>
      <td style="text-align:center">${vv.unidades}</td>
      <td style="text-align:right;font-weight:700">${cop(vv.precio_venta)}</td>
      <td style="text-align:right;color:#E08A8A;font-size:11px">−${cop((vv.comision||0)+(vv.retencion||0)+(vv.costo_envio||0)+(vv.costo_publicidad||0))}<div class="cap" style="font-size:9px">com ${cop(vv.comision||0)} · ret ${cop(vv.retencion||0)}${vv.costo_envio?` · env ${cop(vv.costo_envio)}`:""}${vv.costo_publicidad?` · ads ${cop(vv.costo_publicidad)}`:""}</div></td>
      <td style="text-align:right;font-weight:800;color:var(--green)">${cop(vv.neto_mj)}</td>
      <td style="text-align:right;font-size:11px">${lib}${ads}</td>
    </tr>`;
  }).join("");

  const ventasTable=ventas.length?`<table class="sales mjt"><thead><tr>
      <th>Producto</th><th>Plataforma</th><th style="text-align:center">U</th>
      <th style="text-align:right">Venta</th><th style="text-align:right">Costos</th>
      <th style="text-align:right">Neto María José</th><th style="text-align:right">Liberación</th>
    </tr></thead><tbody>${filas}</tbody></table>`:"";

  // Abonos
  const abonos=r.abonos||[];
  const abFilas=abonos.map(a=>`<tr>
      <td>${mjDate(a.fecha)}</td>
      <td style="font-weight:700;color:var(--amber)">${cop(a.monto)}</td>
      <td>${esc(a.metodo||"—")}</td>
      <td class="muted" style="font-size:11px">${esc(a.nota||"")}</td>
      <td style="text-align:right"><button class="btn-ghost" style="padding:3px 9px;font-size:11px" onclick="mjAbonoDel(${a.id})">✕</button></td>
    </tr>`).join("");
  const abonosBlock=`<div class="card" style="margin-top:18px;padding:16px">
      <div class="row-between" style="margin-bottom:8px"><div style="font-weight:800;font-size:14px">Abonos pagados a María José</div>
        <button class="btn-acc" style="padding:6px 13px;font-size:12px" onclick="mjAbonoModal()">＋ Registrar abono</button></div>
      ${abonos.length?`<table class="sales"><thead><tr><th>Fecha</th><th>Monto</th><th>Método</th><th>Nota</th><th></th></tr></thead><tbody>${abFilas}</tbody></table>`
        :`<div class="muted" style="font-size:12.5px">Aún no has registrado abonos. Cuando le pagues a María José, regístralo aquí y se descuenta del saldo.</div>`}
    </div>`;

  document.getElementById("mjBody").innerHTML=`
    ${platCards?`<div style="display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 14px">${platCards}</div>`:""}
    ${ventasTable?`<div style="font-weight:800;font-size:14px;margin:8px 0">Ventas de sus productos (${ventas.length})</div>${ventasTable}`:""}
    ${abonosBlock}`;
}

function mjAbonoModal(){
  openModal(`<h3>Registrar abono a María José</h3>
    <div class="sub">Un pago hecho a María José. Se descuenta del saldo a pagar.</div>
    <label class="cap">Monto pagado (COP)</label>
    <input id="abMonto" type="number" class="field" placeholder="Ej. 200000" autofocus>
    <label class="cap" style="display:block;margin-top:10px">Fecha</label>
    <input id="abFecha" type="date" class="field" value="${_isoDay(0)}">
    <label class="cap" style="display:block;margin-top:10px">Método (opcional)</label>
    <input id="abMetodo" type="text" class="field" placeholder="Transferencia, Nequi, efectivo…">
    <label class="cap" style="display:block;margin-top:10px">Nota (opcional)</label>
    <input id="abNota" type="text" class="field" placeholder="Ej. abono parcial junio">
    <div id="abErr" class="red" style="font-size:12px;margin-top:8px"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
      <button class="btn-ghost" onclick="closeModal()">Cancelar</button>
      <button class="btn-acc" onclick="mjAbonoSave()">Guardar abono</button>
    </div>`);
}

async function mjAbonoSave(){
  const monto=parseFloat(document.getElementById("abMonto").value||"0");
  const err=document.getElementById("abErr");
  if(!monto||monto<=0){ err.textContent="Ingresa un monto mayor a 0."; return; }
  try{
    await api("/mj/abono",{method:"POST",body:JSON.stringify({
      monto, fecha:document.getElementById("abFecha").value||null,
      metodo:document.getElementById("abMetodo").value||"",
      nota:document.getElementById("abNota").value||""})});
    closeModal(); renderMariaJose();
  }catch(e){ err.textContent=e.message; }
}

async function mjAbonoDel(id){
  if(!confirm("¿Eliminar este abono? El saldo se recalcula.")) return;
  try{ await api("/mj/abono/"+id,{method:"DELETE"}); renderMariaJose(); }
  catch(e){ alert(e.message); }
}

// ── PENDIENTES DE BODEGA ─────────────────────────────────────────────────────
const CANAL_LBL={ml:"MercadoLibre",mercadolibre:"MercadoLibre",shopify_boun:"Shopify BOUN",shopify_kat:"Shopify KAT",falabella:"Falabella",test:"Prueba"};
const CANAL_COL={ml:"#E0A23C",mercadolibre:"#E0A23C",falabella:"#7FB3E0",shopify_boun:"#3FCB82",shopify_kat:"#E68CA8",test:"#9B9A96"};
function canalChip(c){ const lbl=CANAL_LBL[c]||c||"—", col=CANAL_COL[c]||"#9B9A96";
  return `<span style="display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:11px;border:1px solid ${col}55;background:${col}1A;color:${col};font-size:11px;font-weight:700"><span style="width:6px;height:6px;border-radius:50%;background:${col}"></span>${esc(lbl)}</span>`; }
function _fechaHora(s){ if(!s) return ""; try{ const d=new Date(s); return d.toLocaleString("es-CO",{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}); }catch(e){ return s; } }
async function renderCola(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="row-between"><div>
      <div class="page-title">Pendientes de bodega</div>
      <div class="page-sub">Ventas donde ambas bodegas tenían stock: confirma de cuál salió. El total ya se descontó; esto solo cuadra la bodega.</div>
    </div><button class="btn-ghost" onclick="renderCola()">↻ Actualizar</button></div>
    <div id="colaList"><div class="loading"><span class="spinner"></span> Cargando…</div></div>`;
  try{
    const r=await api("/cola-bodega");
    refreshColaBadge();
    const ps=r.pendientes||[];
    if(!ps.length){ document.getElementById("colaList").innerHTML=`<div class="empty" style="text-align:center;padding:48px;color:var(--muted)"><div style="font-size:40px">✓</div><div style="margin-top:8px;font-size:15px">Todo al día</div></div>`; return; }
    document.getElementById("colaList").innerHTML=ps.map(p=>{
      const foto=p.img?`<img src="${esc(p.img)}" loading="lazy" style="width:56px;height:56px;border-radius:10px;object-fit:cover;background:var(--surf);border:1px solid var(--border);flex:none">`
        :`<span style="width:56px;height:56px;border-radius:10px;background:var(--surf);border:1px solid var(--border);flex:none;display:flex;align-items:center;justify-content:center;font-size:22px">📦</span>`;
      return `<div class="card" id="cola-${p.id}" style="display:flex;gap:16px;align-items:center;padding:16px;margin-bottom:10px;flex-wrap:wrap">
        ${foto}
        <div style="flex:1;min-width:220px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span style="font-weight:700;font-size:14px">${esc(p.codigo_boun)} <span class="muted" style="font-weight:400">· ${esc(p.nombre||"")}</span></span>
            ${canalChip(p.canal)}
          </div>
          <div class="muted" style="font-size:12px;margin-top:4px">
            <b style="color:var(--text)">${p.cantidad} u</b> · vendido en <b style="color:var(--text)">${esc(CANAL_LBL[p.canal]||p.canal||"—")}</b>${p.order_id?` · orden #${esc(p.order_id)}`:""} · ${_fechaHora(p.created_at)}
          </div>
          <div class="muted" style="font-size:12px;margin-top:4px">Saldo actual — Bogotá <b style="color:var(--text)">${p.stock_bogota}</b> · Yopal <b style="color:var(--text)">${p.stock_yopal}</b></div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn-acc" style="padding:10px 16px;border-radius:9px" onclick="confirmCola(${p.id},'bogota')">Salió de Bogotá</button>
          <button class="btn-acc" style="padding:10px 16px;border-radius:9px" onclick="confirmCola(${p.id},'yopal')">Salió de Yopal</button>
          <button class="btn-ghost" style="padding:10px 12px;border-radius:9px" title="Vino de ML Full, no descuenta bodega" onclick="fullCola(${p.id})">Full</button>
        </div>
      </div>`;
    }).join("");
  }catch(e){ document.getElementById("colaList").innerHTML=`<div class="red">${esc(e.message)}</div>`; }
}
async function confirmCola(id,bodega){
  const nb=bodega==="bogota"?"Bogotá":"Yopal";
  try{
    const r=await api(`/cola-bodega/${id}/confirmar`,{method:"POST",body:JSON.stringify({bodega})});
    const el=document.getElementById("cola-"+id); if(el) el.remove();
    refreshColaBadge();
    if(!document.querySelector("#colaList .card")) renderCola();
  }catch(e){ alert(e.message); }
}
async function fullCola(id){
  if(!confirm("¿Marcar como venta Full (no descuenta bodega)?")) return;
  try{
    await api(`/cola-bodega/${id}/full`,{method:"POST"});
    const el=document.getElementById("cola-"+id); if(el) el.remove();
    refreshColaBadge();
    if(!document.querySelector("#colaList .card")) renderCola();
  }catch(e){ alert(e.message); }
}

// ── MAPEO DE SKU — publicaciones por vincular al inventario ──────────────────
let MAPEO=null;
let MAPEO_TOUCHED=new Set();  // canales con asignaciones pendientes de aplicar
let MAPEO_SCAN_TIMER=null;
let MAPEO_SEL={}, MAPEO_PRODMAP={}, MAPEO_OPTS_CACHE=null, SKU_OPEN_I=null, SKU_STYLE_DONE=false;
async function renderMapeo(force){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="row-between"><div>
      <div class="page-title">🔗 Mapeo de SKU</div>
      <div class="page-sub">Publicaciones vivas (ML · Falabella · Shopify) que aún no están vinculadas —o están cruzadas— al SKU correcto del inventario BOUN. Asígnalas y el motor sincroniza su stock.</div>
    </div><div style="display:flex;gap:8px;align-items:center"><span id="mapeoApplyWrap"></span><button class="btn-acc" onclick="renderMapeo(true)">↻ Re-escanear</button></div></div>
    <div id="mapeoScanBox"></div>
    <div id="mapeoKpis" class="kpis"></div>
    <div id="mapeoBody"><div class="loading"><span class="spinner"></span> Auditando MercadoLibre, Falabella y Shopify…</div></div>`;
  loadMapeo(force===true);
}
async function loadMapeo(force){
  if(force) document.getElementById("mapeoBody").innerHTML=`<div class="loading"><span class="spinner"></span> Re-escaneando los canales…</div>`;
  try{
    const r=await api("/mapeo"+(force?"?force=1":""));
    MAPEO=r; refreshMapeoBadge(); drawMapeoKpis(r); drawMapeo(); updateMapeoApplyBtn();
  }catch(e){ document.getElementById("mapeoBody").innerHTML=`<div class="red">${esc(e.message)}</div>`; }
}
function drawMapeoKpis(r){
  // ── Panel de CONFIRMACIÓN DE COHERENCIA (segundo método: la reconciliación
  //    por canal debe cuadrar por partida doble; solo entonces es verde). ──
  const rec=r.reconciliacion||{};
  const algunCaido=CH_ORDER.some(c=>rec[c]&&!rec[c].respondio);
  const verde=!!r.coherencia;
  const head= verde
    ? `<div style="font-size:15px;font-weight:800;color:var(--green)">✅ Coherencia verificada</div>
       <div class="muted" style="font-size:12px;margin-top:2px">Cada publicación viva cuadra con su SKU y no hay vínculos huérfanos. Confirmado por reconciliación, no por ausencia de alertas.</div>`
    : algunCaido
    ? `<div style="font-size:15px;font-weight:800;color:var(--amber)">⚠ Verificación parcial</div>
       <div class="muted" style="font-size:12px;margin-top:2px">Un canal no respondió: no se puede confirmar el 100%. Reintenta el re-escaneo.</div>`
    : `<div style="font-size:15px;font-weight:800;color:var(--amber)">⚠ Hay diferencias por resolver</div>
       <div class="muted" style="font-size:12px;margin-top:2px">La reconciliación no cuadra: revisa los pendientes de abajo.</div>`;
  const rows=CH_ORDER.filter(c=>rec[c]).map(c=>{ const m=chMeta(c), x=rec[c];
    const estado = !x.respondio ? `<span style="color:var(--red)">no respondió</span>`
      : x.ok ? `<span style="color:var(--green)">✓ cuadra</span>`
      : `<span style="color:var(--amber)">⚠ revisar</span>`;
    const detalle = x.respondio
      ? `${x.vivas} vivas · ${x.mapeadas} mapeadas · ${x.sin_mapear} sin mapear · ${x.cruzados} cruzado(s) · ${x.huerfanos} huérfano(s)`
      : (x.error||"sin conexión");
    return `<div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-top:1px solid var(--border)">
      <span class="ch-count" style="background:${m.col}">${esc(m.short)}</span>
      <span style="font-size:12px;flex:1;min-width:160px" class="muted">${esc(detalle)}</span>
      <span style="font-size:12px;font-weight:700">${estado}</span></div>`; }).join("");
  document.getElementById("mapeoKpis").innerHTML=`
    <div style="display:flex;gap:10px;flex-wrap:wrap;width:100%">
      <div class="kpi" style="min-width:96px"><div class="cap">Sin mapear</div><div class="val">${r.n_sin_mapear||0}</div></div>
      <div class="kpi" style="min-width:96px"><div class="cap">SKU cruzado</div><div class="val">${r.n_mal_mapeado||0}</div></div>
      <div class="kpi" style="min-width:96px"><div class="cap">Huérfanos</div><div class="val">${r.n_huerfano||0}</div></div>
    </div>
    <div class="card" style="padding:14px 16px;margin:10px 0 4px;border-color:${verde?'var(--green)':'var(--amber)'}">
      ${head}
      <div style="margin-top:8px">${rows||'<span class="muted" style="font-size:12px">Sin canales auditados.</span>'}</div>
    </div>`;
}
function skuThumb(th,s){ s=s||34; return th?`<img src="${esc(th)}" loading="lazy" style="width:${s}px;height:${s}px;border-radius:6px;object-fit:cover;background:var(--bg);border:1px solid var(--border);flex:none">`:`<span style="width:${s}px;height:${s}px;border-radius:6px;background:var(--bg);border:1px solid var(--border);flex:none;display:flex;align-items:center;justify-content:center;font-size:${Math.round(s*0.5)}px">🏷️</span>`; }
function skuBtnLabel(i){
  const p=MAPEO_SEL[i]?MAPEO_PRODMAP[MAPEO_SEL[i]]:null;
  if(!p) return `<span class="muted" style="font-size:12px;flex:1">— elegir SKU —</span><span style="color:var(--muted)">▾</span>`;
  return `${skuThumb(p.thumb,26)}<span style="font-size:12px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><b>${esc(p.code)}</b> · ${esc(p.name)}</span><span style="color:var(--muted)">▾</span>`;
}
function skuOptsHTML(){
  if(MAPEO_OPTS_CACHE!=null) return MAPEO_OPTS_CACHE;
  MAPEO_OPTS_CACHE=((MAPEO&&MAPEO.productos)||[]).map(p=>`<div class="skuopt" data-pid="${p.id}" data-txt="${esc(((p.code||"")+" "+(p.name||"")).toLowerCase())}" onclick="skuChoose(this)" style="display:flex;align-items:center;gap:8px;padding:6px 8px;cursor:pointer;border-radius:7px;margin:0 4px">${skuThumb(p.thumb,34)}<span style="font-size:12px;line-height:1.25"><b>${esc(p.code)}</b> · ${esc(p.name)}</span></div>`).join("");
  return MAPEO_OPTS_CACHE;
}
function skuControl(i){
  return `<div class="skuwrap" style="position:relative;min-width:230px;flex:none"><button type="button" class="field fmini" id="skubtn-${i}" onclick="skuOpen(${i},event)" style="display:flex;align-items:center;gap:7px;width:100%;cursor:pointer;height:34px;padding:0 8px">${skuBtnLabel(i)}</button><div class="skupanel" id="skupanel-${i}" style="display:none"></div></div>`;
}
function ensureSkuStyle(){
  if(SKU_STYLE_DONE) return; SKU_STYLE_DONE=true;
  const st=document.createElement("style");
  st.textContent=".skuopt:hover{background:var(--card)}";
  document.head.appendChild(st);
  document.addEventListener("click",e=>{ if(SKU_OPEN_I!=null && !e.target.closest(".skuwrap")) skuCloseAll(); });
}
function skuOpen(i,ev){
  if(ev) ev.stopPropagation();
  ensureSkuStyle();
  if(SKU_OPEN_I===i){ skuCloseAll(); return; }
  skuCloseAll();
  const panel=document.getElementById("skupanel-"+i); if(!panel) return;
  panel.innerHTML=`<input class="field fmini" id="skusearch-${i}" placeholder="Buscar SKU o nombre…" oninput="skuFilter(${i},this.value)" onclick="event.stopPropagation()" style="width:calc(100% - 12px);margin:6px;position:sticky;top:6px"><div id="skulist-${i}" style="padding-bottom:6px">${skuOptsHTML()}</div>`;
  panel.style.cssText="display:block;position:absolute;top:calc(100% + 4px);left:0;min-width:280px;max-width:360px;z-index:60;background:var(--surf);border:1px solid var(--border);border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.45);max-height:320px;overflow:auto";
  SKU_OPEN_I=i;
  const s=document.getElementById("skusearch-"+i); if(s) s.focus();
}
function skuFilter(i,q){
  q=(q||"").toLowerCase().trim();
  document.querySelectorAll("#skulist-"+i+" .skuopt").forEach(el=>{ el.style.display=(!q||el.dataset.txt.indexOf(q)>=0)?"flex":"none"; });
}
function skuChoose(el){
  if(SKU_OPEN_I==null) return;
  const i=SKU_OPEN_I; MAPEO_SEL[i]=+el.dataset.pid;
  const b=document.getElementById("skubtn-"+i); if(b) b.innerHTML=skuBtnLabel(i);
  skuCloseAll();
}
function skuCloseAll(){
  document.querySelectorAll(".skupanel").forEach(p=>{ p.style.display="none"; p.innerHTML=""; });
  SKU_OPEN_I=null;
}
function drawMapeo(){
  const r=MAPEO; if(!r)return;
  const ps=(r.pendientes||[]).filter(x=>x&&!x._resuelto);
  const body=document.getElementById("mapeoBody");
  if(!ps.length){ body.innerHTML=`<div class="empty" style="text-align:center;padding:40px;color:var(--muted)"><div style="font-size:40px">✓</div><div style="margin-top:8px;font-size:15px">Sin pendientes — cada publicación viva tiene su SKU y no hay huérfanos.</div></div>`; return; }
  const opt=(sug)=>`<option value="">— elegir SKU —</option>`+(r.productos||[]).map(p=>`<option value="${p.id}" ${sug&&p.code&&p.code.toUpperCase()===String(sug).toUpperCase()?"selected":""}>${esc(p.code)} · ${esc(p.name)}</option>`).join("");
  MAPEO_SEL={}; MAPEO_PRODMAP={}; MAPEO_OPTS_CACHE=null;
  (r.productos||[]).forEach(pr=>{ MAPEO_PRODMAP[pr.id]=pr; });
  const _code2id={}; (r.productos||[]).forEach(pr=>{ if(pr.code) _code2id[String(pr.code).toUpperCase()]=pr.id; });
  const MOT={sin_mapear:["SIN MAPEAR","#E0A23C","#0A0A0A"],mal_mapeado:["SKU CRUZADO","#E11D48","#fff"],huerfano:["VÍNCULO HUÉRFANO","#C58CE6","#0A0A0A"]};
  body.innerHTML=ps.map(p=>{
    const i=r.pendientes.indexOf(p);
    if(p.sugerido_code && _code2id[String(p.sugerido_code).toUpperCase()]) MAPEO_SEL[i]=_code2id[String(p.sugerido_code).toUpperCase()];
    const foto=p.thumb?`<img src="${esc(p.thumb)}" loading="lazy" style="width:64px;height:64px;border-radius:10px;object-fit:cover;background:var(--surf);border:1px solid var(--border);flex:none">`
      :`<span style="width:64px;height:64px;border-radius:10px;background:var(--surf);border:1px solid var(--border);flex:none;display:flex;align-items:center;justify-content:center;font-size:24px">🏷️</span>`;
    const mt=MOT[p.motivo]||MOT.sin_mapear;
    const motivo=`<span style="background:${mt[1]};color:${mt[2]};font-size:10px;font-weight:800;padding:2px 8px;border-radius:20px">${mt[0]}</span>`;
    const link=p.link?`<a href="${esc(p.link)}" target="_blank" rel="noopener" class="btn-ghost" style="padding:7px 12px;border-radius:8px;text-decoration:none">Ver ↗</a>`:`<span class="muted" style="font-size:11px">sin link</span>`;
    const acciones = p.motivo==="huerfano"
      ? `${link}
         ${skuControl(i)}
         <button class="btn-acc" style="padding:9px 14px;border-radius:9px" onclick="asociarMapeo(${i})">Re-mapear</button>
         <button class="btn-ghost" style="padding:9px 12px;border-radius:9px" onclick="quitarHuerfano(${i})">Quitar vínculo</button>`
      : `${link}
         ${skuControl(i)}
         <button class="btn-acc" style="padding:9px 16px;border-radius:9px" onclick="asociarMapeo(${i})">Asociar</button>`;
    return `<div class="card" id="mp2-${i}" style="display:flex;gap:16px;align-items:center;padding:16px;margin-bottom:10px;flex-wrap:wrap">
      ${foto}
      <div style="flex:1;min-width:240px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">${chBadge(p.channel)} ${motivo}</div>
        <div style="font-weight:650;font-size:14px;line-height:1.3">${esc(p.title)}</div>
        <div class="muted" style="font-size:11.5px;margin-top:4px">${esc(p.ext_id)}${p.sku_canal?` · SKU canal: <b style="color:var(--text)">${esc(p.sku_canal)}</b>`:""}${p.qty?` · ${p.qty} u`:""}${p.price?` · ${cop(p.price)}`:""}</div>
        ${p.detalle?`<div class="muted" style="font-size:11.5px;margin-top:3px">${esc(p.detalle)}</div>`:""}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">${acciones}</div>
    </div>`;
  }).join("");
}
async function quitarHuerfano(i){
  const p=(MAPEO&&MAPEO.pendientes)?MAPEO.pendientes[i]:null; if(!p)return;
  if(!confirm("¿Quitar el vínculo huérfano? El inventario dejará de creer que esa publicación existe.")) return;
  try{
    await api("/mapeo/desvincular",{method:"POST",body:JSON.stringify({channel:p.channel,ext_id:p.ext_id})});
    MAPEO_TOUCHED.add(p.channel); updateMapeoApplyBtn();
    p._resuelto=true;
    const el=document.getElementById("mp2-"+i);
    if(el){ el.style.transition="opacity .25s"; el.style.opacity="0"; setTimeout(()=>el.remove(),250); }
    refreshMapeoBadge();
    if(!MAPEO.pendientes.some(x=>x&&!x._resuelto)) setTimeout(()=>loadMapeo(true),300);
  }catch(e){ alert(e.message); }
}
async function asociarMapeo(i){
  const p=(MAPEO&&MAPEO.pendientes)?MAPEO.pendientes[i]:null; if(!p)return;
  const pid=MAPEO_SEL[i]||0;
  if(!pid){ alert("Elige el SKU del inventario al que pertenece esta publicación."); return; }
  const m=p._meta||{};
  try{
    await api("/mapeo/asociar",{method:"POST",body:JSON.stringify({
      channel:p.channel, ext_id:p.ext_id, product_id:pid,
      title:m.title||p.title, thumb:m.thumb||p.thumb, qty:m.qty||p.qty,
      price:m.price||p.price, logistic:m.logistic||"", inv_id:m.inv_id||"", upid:m.upid||""})});
    MAPEO_TOUCHED.add(p.channel); updateMapeoApplyBtn();
    p._resuelto=true;
    const el=document.getElementById("mp2-"+i);
    if(el){ el.style.transition="opacity .25s"; el.style.opacity="0"; setTimeout(()=>el.remove(),250); }
    refreshMapeoBadge();
    if(!MAPEO.pendientes.some(x=>x&&!x._resuelto)) setTimeout(()=>drawMapeo(),300);
  }catch(e){ alert(e.message); }
}

// ── Aplicar stock a lo asignado (Mapeo → reconciliación de los canales tocados) ──
function updateMapeoApplyBtn(){
  const wrap=document.getElementById("mapeoApplyWrap"); if(!wrap) return;
  if(!isAdmin() || !MAPEO_TOUCHED.size){ wrap.innerHTML=""; return; }
  const labels=[...MAPEO_TOUCHED].map(c=>chMeta(c).short).join(", ");
  wrap.innerHTML=`<button class="btn-acc" style="background:#3FCB82;color:#0A0A0A" onclick="aplicarMapeoStock()" title="Reconcilia el stock real en los canales que acabas de tocar">⤓ Aplicar stock a lo asignado · ${esc(labels)}</button>`;
}
async function aplicarMapeoStock(){
  const chans=[...MAPEO_TOUCHED]; if(!chans.length) return;
  const labels=chans.map(c=>chMeta(c).lbl).join(", ");
  if(!confirm("Vas a APLICAR (escribir) el stock real de tu inventario en: "+labels+".\n\nReconcilia TODAS las publicaciones de esos canales (excepto Full y catálogo) al disponible real, incluidas las que acabas de asignar.\n\n¿Confirmas?")) return;
  try{
    await api("/sync/scan-start",{method:"POST",body:JSON.stringify({mode:"apply",channels:chans})});
    MAPEO_TOUCHED.clear(); updateMapeoApplyBtn();
    if(typeof scanGlobalPoll==="function") scanGlobalPoll();
    mapeoScanPoll(labels);
  }catch(e){
    if(/curso/i.test(e.message||"")){ if(typeof scanGlobalPoll==="function") scanGlobalPoll(); mapeoScanPoll(labels); }
    else alert(e.message);
  }
}

async function mapeoScanPoll(labels){
  if(MAPEO_SCAN_TIMER){ clearInterval(MAPEO_SCAN_TIMER); MAPEO_SCAN_TIMER=null; }
  const bar=(pct,col)=>`<div style="height:8px;background:var(--border);border-radius:6px;overflow:hidden;margin-top:7px"><div style="height:100%;width:${pct}%;background:${col};transition:width .3s"></div></div>`;
  const render=(html)=>{ const b=document.getElementById("mapeoScanBox"); if(b) b.innerHTML=html; };
  render(`<div class="card" style="padding:12px 14px;border-color:#3FCB82"><div style="font-size:13px;font-weight:700">⤓ Aplicando stock · ${esc(labels)}</div><div class="muted" style="font-size:12px;margin-top:2px">Iniciando reconciliación…</div>${bar(4,'#3FCB82')}</div>`);
  let polls=0;
  const tick=async()=>{
    polls++;
    let s=null;
    try{ const r=await fetch("/api/sync/scan-status",{headers: TOKEN?{"Authorization":"Bearer "+TOKEN}:{}}); if(r.ok) s=await r.json(); }catch(e){}
    if(!s) return;
    if(s.status==="running"){
      const done=s.done||0,total=s.total||0,pct=total?Math.round(done/total*100):0;
      render(`<div class="card" style="padding:12px 14px;border-color:#3FCB82"><div style="font-size:13px;font-weight:700">⤓ Aplicando stock · ${esc(labels)}</div><div class="muted" style="font-size:12px;margin-top:2px"><b style="color:var(--text)">${done}/${total}</b> publicaciones · ${pct}%</div>${bar(pct||4,'#3FCB82')}</div>`);
    } else if(s.status==="done"){
      clearInterval(MAPEO_SCAN_TIMER); MAPEO_SCAN_TIMER=null;
      const c=s.counts||{};
      const resumen=`${c.escritos||0} escritas · ${c.reactivadas||0} reactivadas · ${c.sin_cambio||0} sin cambio${c.errores?` · ${c.errores} con error`:""}`;
      render(`<div class="card" style="padding:12px 14px;border-color:#3FCB82"><div style="font-size:13px;font-weight:700;color:var(--green)">✓ Reconciliación lista · ${esc(labels)}</div><div class="muted" style="font-size:12px;margin-top:2px">${esc(resumen)}</div>${bar(100,'#3FCB82')}</div>`);
      setTimeout(()=>render(""), 9000);
      loadMapeo(true);
    } else if(s.status==="error"){
      clearInterval(MAPEO_SCAN_TIMER); MAPEO_SCAN_TIMER=null;
      render(`<div class="card" style="padding:12px 14px;border-color:var(--red)"><div class="red" style="font-size:13px;font-weight:700">⚠ El escaneo falló</div><div class="muted" style="font-size:12px;margin-top:2px">${esc(s.error||"Reintenta en un momento.")}</div></div>`);
    } else if(polls>3){
      clearInterval(MAPEO_SCAN_TIMER); MAPEO_SCAN_TIMER=null; render("");
    }
  };
  await tick();
  MAPEO_SCAN_TIMER=setInterval(tick, 1500);
}

// ── DENUNCIAS (Brand Protection Program) ─────────────────────────────────────
let DENUNCIAS=null;
const DEN_EST={
  pendiente:["PENDIENTE","#E0A23C","#0A0A0A"],
  en_proceso:["EN PROCESO","#2D8CFF","#fff"],
  procedente:["PROCEDENTE","#16A34A","#fff"],
  publicacion_inactiva:["PUBLICACIÓN CAÍDA","#16A34A","#fff"],
  rechazada:["RECHAZADA","#E11D48","#fff"],
};
function denFecha(s){ if(!s)return"—"; try{return new Date(s).toLocaleDateString("es-CO",{day:"2-digit",month:"short",year:"numeric"});}catch(e){return s;} }
let DEN_VIEW="activas"; // activas | ganadas | rechazadas | todas
function setDenView(v){ DEN_VIEW=v; if(typeof DENUNCIAS!=="undefined"&&DENUNCIAS){ drawDenKpis(DENUNCIAS); drawDenuncias(); } }
async function renderDenuncias(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="row-between"><div>
      <div class="page-title">🛡 Denuncias · Protección de marca</div>
      <div class="page-sub">Vendedores que se cuelgan de tus catálogos BOUN o usan tu marca registrada sin autorización. La skill los denuncia en el Brand Protection Program de MercadoLibre cada día (8:00 PM) y aquí sigues el estado de cada caso.</div>
    </div><button class="btn-acc" onclick="renderDenuncias()">↻ Actualizar</button></div>
    <div id="denKpis" class="kpis"></div>
    <div id="denBody"><div class="loading"><span class="spinner"></span> Cargando denuncias…</div></div>`;
  try{
    const r=await api("/denuncias");
    DENUNCIAS=r; refreshDenunciasBadge(); drawDenKpis(r); drawDenuncias();
  }catch(e){ document.getElementById("denBody").innerHTML=`<div class="red">${esc(e.message)}</div>`; }
}
function drawDenKpis(r){
  const c=r.counts||{};
  const caidas=(c.procedente||0)+(c.publicacion_inactiva||0);
  const activas=(c.en_proceso||0)+(c.pendiente||0);
  const sel=v=>DEN_VIEW===v?"outline:2px solid var(--acc);outline-offset:-2px;":"";
  document.getElementById("denKpis").innerHTML=`
    <div style="display:flex;gap:10px;flex-wrap:wrap;width:100%">
      <div class="kpi" title="Ver todas" style="min-width:96px;cursor:pointer;${sel('todas')}" onclick="setDenView('todas')"><div class="cap">Total</div><div class="val">${c.total||0}</div></div>
      <div class="kpi" title="Ver activas" style="min-width:96px;cursor:pointer;${sel('activas')}" onclick="setDenView('activas')"><div class="cap">En proceso</div><div class="val">${activas}</div></div>
      <div class="kpi" title="Ver caídas / ganadas" style="min-width:96px;cursor:pointer;${sel('ganadas')}" onclick="setDenView('ganadas')"><div class="cap">Caídas / ganadas</div><div class="val" style="color:var(--green)">${caidas}</div></div>
      <div class="kpi" title="Ver rechazadas" style="min-width:96px;cursor:pointer;${sel('rechazadas')}" onclick="setDenView('rechazadas')"><div class="cap">Rechazadas</div><div class="val">${c.rechazada||0}</div></div>
    </div>`;
}
function drawDenuncias(){
  const r=DENUNCIAS; if(!r)return;
  const RESUELTAS=["procedente","publicacion_inactiva","rechazada"];
  let ds=r.denuncias||[];
  if(DEN_VIEW==="activas") ds=ds.filter(d=>!RESUELTAS.includes(d.estado));
  else if(DEN_VIEW==="ganadas") ds=ds.filter(d=>d.estado==="procedente"||d.estado==="publicacion_inactiva");
  else if(DEN_VIEW==="rechazadas") ds=ds.filter(d=>d.estado==="rechazada");
  const body=document.getElementById("denBody");
  if(!ds.length){
    const m = DEN_VIEW==="ganadas" ? "Aún no hay denuncias caídas o ganadas. Cuando una denuncia se apruebe o la publicación caiga, aparecerá aquí con su historial."
      : DEN_VIEW==="rechazadas" ? "No hay denuncias rechazadas."
      : DEN_VIEW==="activas" ? "No hay denuncias activas. Las resueltas están en «Caídas / ganadas» y «Rechazadas» (haz clic en esos indicadores)."
      : "Aún no hay denuncias registradas. La skill las irá agregando en su corrida diaria.";
    body.innerHTML=`<div class="empty" style="text-align:center;padding:40px;color:var(--muted)"><div style="font-size:40px">🛡</div><div style="margin-top:8px;font-size:15px">${m}</div></div>`; return; }
  body.innerHTML=ds.map((d,i)=>{
    const est=DEN_EST[d.estado]||["—","#666","#fff"];
    const badge=`<span style="background:${est[1]};color:${est[2]};font-size:10px;font-weight:800;padding:2px 8px;border-radius:20px">${est[0]}</span>`;
    const foto=d.thumb?`<img src="${esc(d.thumb)}" loading="lazy" style="width:64px;height:64px;border-radius:10px;object-fit:cover;background:var(--surf);border:1px solid var(--border);flex:none">`
      :`<span style="width:64px;height:64px;border-radius:10px;background:var(--surf);border:1px solid var(--border);flex:none;display:flex;align-items:center;justify-content:center;font-size:24px">🛡️</span>`;
    const lpub=d.pub_link?`<a href="${esc(d.pub_link)}" target="_blank" rel="noopener" class="btn-ghost" style="padding:6px 11px;border-radius:8px;text-decoration:none">Publicación infractora ↗</a>`:"";
    const lcat=d.catalog_link?`<a href="${esc(d.catalog_link)}" target="_blank" rel="noopener" class="btn-ghost" style="padding:6px 11px;border-radius:8px;text-decoration:none">Catálogo usurpado ↗</a>`:"";
    const lsell=d.seller_link?`<a href="${esc(d.seller_link)}" target="_blank" rel="noopener" class="btn-ghost" style="padding:6px 11px;border-radius:8px;text-decoration:none">Vendedor ↗</a>`:"";
    const hist=(d.historial&&d.historial.length)?`<details style="margin-top:8px"><summary style="cursor:pointer;font-size:11.5px;color:var(--muted)">Historial (${d.historial.length})</summary>
        <div style="margin-top:6px;border-left:2px solid var(--border);padding-left:10px">${d.historial.map(h=>`<div style="font-size:11.5px;margin-bottom:3px"><b>${denFecha(h.fecha)}</b> · ${esc((DEN_EST[h.estado]||[h.estado])[0])}${h.nota?` — <span class="muted">${esc(h.nota)}</span>`:""}</div>`).join("")}</div></details>`:"";
    return `<div class="card" style="display:flex;gap:16px;align-items:flex-start;padding:16px;margin-bottom:10px;flex-wrap:wrap">
      ${foto}
      <div style="flex:1;min-width:260px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">${badge}
          <span style="font-weight:800;font-size:14px">${esc(d.seller_nick)}</span>
          <span class="muted" style="font-size:11px">denunciado ${denFecha(d.denunciado_at)}</span></div>
        <div style="font-weight:600;font-size:13.5px;line-height:1.3">${esc(d.pub_title||d.catalog_title||d.pub_id||"")}</div>
        <div class="muted" style="font-size:11.5px;margin-top:4px">
          ${d.pub_id?`Pub: <b style="color:var(--text)">${esc(d.pub_id)}</b> · `:""}Catálogo: <b style="color:var(--text)">${esc(d.catalog_id)}</b>${d.pub_price?` · ${cop(d.pub_price)}`:""}
          · Motivo: ${esc(d.tipo_infraccion||d.motivo||"marca registrada")}
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:9px">${lpub} ${lcat} ${lsell}</div>
        ${hist}
      </div>
      <div class="muted" style="font-size:11px;text-align:right;min-width:96px">Última revisión<br><b style="color:var(--text)">${denFecha(d.revisado_at)}</b></div>
    </div>`;
  }).join("");
}

// ── MIS PRODUCTOS ────────────────────────────────────────────────────────────
let MP=[], MP_SUM={}, MP_SORT="star_score", MP_DESC=true, MP_DAYS=60;
let MP_F={q:"",cat:"",camp:"",status:"",star:""}, MP_OPEN=null;
async function renderMyProducts(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="row-between"><div>
      <div class="page-title">Mis Productos</div>
      <div class="page-sub">Tus publicaciones de MercadoLibre con datos reales: ventas, publicidad y rentabilidad.</div>
    </div><div style="display:flex;gap:8px;align-items:center">
      <span id="mpAge" class="muted" style="font-size:11px"></span>
      <button class="btn-ghost" onclick="exportMP()">⬇ Exportar datos</button>
      <button class="btn-acc" onclick="loadMP(true)">↻ Actualizar</button></div></div>
    <div id="mpKpis" class="kpis"></div>
    <div id="mpFilters" class="filters"></div>
    <div id="mpBody"><div class="loading"><span class="spinner"></span> Cargando datos de MercadoLibre…</div></div>`;
  loadMP();
}
async function loadMP(force){
  if(force) document.getElementById("mpBody").innerHTML=`<div class="loading"><span class="spinner"></span> Actualizando desde MercadoLibre…</div>`;
  try{ const r=await api("/my-products?days="+MP_DAYS+(force?"&force=true":""));
    if(!r.ok){ document.getElementById("mpBody").innerHTML=`<div class="red">${r.error||"Error"}</div>`; return; }
    MP=r.products; MP_SUM=r.summary; drawMPFilters(); drawMP();
    const age=r.cache_age_min||0, ageEl=document.getElementById("mpAge");
    if(ageEl) ageEl.textContent = age<1?"datos al momento":(age<60?`datos de hace ${age} min`:`datos de hace ${Math.floor(age/60)} h`);
  }catch(e){ document.getElementById("mpBody").innerHTML=`<div class="red">${e.message}</div>`; }
}
function drawMPFilters(){
  const cats=[...new Set(MP.map(p=>p.category_name).filter(Boolean))].sort();
  document.getElementById("mpFilters").innerHTML=`
    <input class="field fmini" placeholder="Buscar…" value="${esc(MP_F.q)}" oninput="MP_F.q=this.value;drawMP()">
    <select class="field fmini" onchange="MP_F.cat=this.value;drawMP()">
      <option value="">Categoría: todas</option>${cats.map(c=>`<option ${MP_F.cat===c?"selected":""}>${esc(c)}</option>`).join("")}</select>
    <select class="field fmini" onchange="MP_F.status=this.value;drawMP()">
      <option value="">Estado: todos</option><option value="active" ${MP_F.status==="active"?"selected":""}>Activos</option><option value="paused" ${MP_F.status==="paused"?"selected":""}>Pausados</option></select>
    <select class="field fmini" onchange="MP_F.camp=this.value;drawMP()">
      <option value="">Publicidad: toda</option><option value="con" ${MP_F.camp==="con"?"selected":""}>Con campaña</option><option value="sin" ${MP_F.camp==="sin"?"selected":""}>Sin campaña</option></select>
    <select class="field fmini" onchange="MP_F.star=this.value;drawMP()">
      <option value="">Todos</option><option value="star" ${MP_F.star==="star"?"selected":""}>★ Estrella (top 20)</option><option value="restock" ${MP_F.star==="restock"?"selected":""}>A reponer</option></select>
    <select class="field fmini" onchange="MP_DAYS=+this.value;loadMP()">
      ${[7,15,30,60].map(d=>`<option value="${d}" ${MP_DAYS===d?"selected":""}>${d} días</option>`).join("")}</select>`;
}
function drawMP(){
  const s=MP_SUM, k=s.ads_kpis||{}, d=MP_DAYS;
  const fmt=n=>(n||0).toLocaleString("es-CO");
  // Fila 1: resumen general (igual que escritorio)
  const row1=[
    ["Productos",fmt(s.total_products||MP.length),"acc"],
    [`Vendidos ${d}d`,fmt(s.total_sold_60d||0),"text"],
    [`Neto ${d}d`,cop(s.total_net_60d||0),(s.total_net_60d>=0?"green":"red")],
    [`Gasto Ads ${d}d`,cop(s.total_ad_cost||0),"amber"],
    ["A reponer",fmt(s.need_restock||0),"red"],
  ];
  // Fila 2: publicidad (Product Ads)
  const row2=[
    ["Ventas por publicidad",fmt(k.ventas_producto||0),"green"],
    ["Ventas sin publicidad",fmt(k.ventas_sin_prod||0),"muted"],
    ["ROAS",(k.roas||0)+"x","green"],
    ["Ingresos Ads",cop(k.ingresos||0),"green"],
    ["Inversión Ads",cop(k.inversion||0),"amber"],
    ["ACOS",(k.acos||0)+"%",(k.acos<=20?"green":k.acos<=30?"amber":"red")],
  ];
  const card=([c,vv,cl])=>`<div class="kpi"><div class="cap">${c}</div><div class="val ${cl}">${vv}</div></div>`;
  document.getElementById("mpKpis").innerHTML=
    `<div class="kpis" style="margin:0 0 6px 0;width:100%">${row1.map(card).join("")}</div>`+
    `<div class="cap" style="margin:4px 0 4px;color:var(--muted);font-size:11px;width:100%">PUBLICIDAD (Product Ads) — periodo seleccionado</div>`+
    `<div class="kpis" style="margin:0;width:100%">${row2.map(card).join("")}</div>`;
  let data=MP.filter(p=>{
    const f=MP_F;
    if(f.q && !((p.title||"").toLowerCase().includes(f.q.toLowerCase())))return false;
    if(f.cat && p.category_name!==f.cat)return false;
    if(f.status && p.status!==f.status)return false;
    if(f.camp==="con" && !p.has_campaign)return false;
    if(f.camp==="sin" && p.has_campaign)return false;
    if(f.star==="star" && !p.is_star)return false;
    if(f.star==="restock" && !(p.restock_qty>0))return false;
    return true;
  });
  data.sort((a,b)=>{ let x=a[MP_SORT],y=b[MP_SORT];
    if(MP_SORT==="title"){x=(x||"").toLowerCase();y=(y||"").toLowerCase(); return MP_DESC?(x<y?1:-1):(x>y?1:-1);}
    return MP_DESC?(y||0)-(x||0):(x||0)-(y||0); });
  const cols=[["","#"],["","★"],["","Foto"],["title","Producto"],["price","Precio"],["cost","Costo"],
    ["inventory","Inv."],["sold_60d","Vend"],["ad_cost","Ads $"],["ad_acos","ACOS"],["ad_roas","ROAS"],
    ["net_unit","Neto/u"],["margin_pct","Margen"],["net_60d","Neto "+MP_DAYS+"d"],["restock_qty","Reponer"]];
  let html=`<table class="mp"><thead><tr>${cols.map(([f,t])=>
    f?`<th onclick="sortMP('${f}')">${t}${MP_SORT===f?(MP_DESC?" ▼":" ▲"):""}</th>`:`<th>${t}</th>`).join("")}</tr></thead><tbody>`;
  data.forEach((p,i)=>{
    const m=+p.margin_pct||0, mc=m>=20?"green":m>=8?"amber":"red";
    const nc=(+p.net_60d>=0)?"green":"red", roas=+p.ad_roas||0;
    const rc=roas>=3?"green":roas>=1?"amber":(roas===0?"muted":"red");
    const url=p.permalink||("https://articulo.mercadolibre.com.co/"+(p.item_id||"").replace("MCO","MCO-"));
    let t=(p.title||""); if(t.length>34)t=t.slice(0,34)+"…";
    const op=(+p.original_price>+p.price)?`<span class="strike">${cop(p.original_price)}</span>`:"";
    const sku=p.inv_code?`<span class="sku">📦${esc(p.inv_code)}</span>`:"";
    html+=`<tr class="mprow" onclick="toggleMP('${p.item_id}')">
      <td class="${p.is_star?'acc':'muted'}">${(p.rank||i+1)}</td>
      <td>${p.is_star?'<span class="acc">★</span>':''}</td>
      <td>${p.thumbnail?`<img class="th" src="${p.thumbnail}">`:`<div class="th"></div>`}</td>
      <td><a href="${url}" target="_blank" onclick="event.stopPropagation()" style="color:var(--acc);text-decoration:none" title="${esc(p.title)}">${esc(t)}</a> ${sku}
        <div class="pmeta">${p.item_id}</div></td>
      <td>${cop(p.price)} ${op}</td>
      <td class="${p.cost_known?'green':'red'}">${p.cost_known?cop(p.cost):"—"}</td>
      <td>${p.inventory}</td><td><b>${p.sold_60d}</b></td>
      <td class="amber">${cop(p.ad_cost)}</td>
      <td class="muted">${(+p.ad_acos||0).toFixed(1)}%</td>
      <td class="${rc}">${roas?roas.toFixed(2)+"x":"—"}</td>
      <td class="${nc}">${cop(p.net_unit)}</td>
      <td class="${mc}">${m.toFixed(1)}%</td>
      <td class="${nc}"><b>${cop(p.net_60d)}</b></td>
      <td class="${p.restock_qty>0?'red':'muted'}">${p.restock_qty>0?"+"+p.restock_qty:"—"}</td></tr>`;
    if(MP_OPEN===p.item_id){
      html+=`<tr class="mpdetail"><td colspan="15"><div id="mpd-${p.item_id}">${mpAdsPanel(p)}<div class="note" id="mpt-${p.item_id}"><span class="spinner"></span> Conectando con Google Trends…</div></div></td></tr>`;
    }
  });
  html+="</tbody></table>";
  if(!data.length) html=`<div class="loading">Sin productos que coincidan.</div>`;
  document.getElementById("mpBody").innerHTML=html;
  if(MP_OPEN){ const p=MP.find(x=>x.item_id===MP_OPEN); if(p) loadMPTrends(p); }
}
function mpAdsPanel(p){
  const cards=[["Ventas por publicidad",p.ad_dir_units||0],["Ventas sin publicidad",p.ad_indir_units||0],
    ["ROAS",(+p.ad_roas||0).toFixed(2)+"x"],["Ingresos Ads",cop(p.ad_sales)],["Inversión Ads",cop(p.ad_cost)],
    ["ACOS",(+p.ad_acos||0).toFixed(1)+"%"],["Clics",p.ad_clicks||0],["Impresiones",p.ad_prints||0],["CPC",cop(p.ad_cpc)]];
  return `<div class="kpis" style="margin:4px 0">${cards.map(([c,v])=>`<div class="kpi" style="min-width:110px;padding:8px 12px"><div class="cap">${c}</div><div class="val" style="font-size:14px">${v}</div></div>`).join("")}</div>`;
}
async function toggleMP(iid){ MP_OPEN=MP_OPEN===iid?null:iid; drawMP(); }
async function loadMPTrends(p){
  try{ const r=await api(`/product-trends?item_id=${encodeURIComponent(p.item_id)}&title=${encodeURIComponent(p.title||"")}&days=${MP_DAYS}`);
    const el=document.getElementById("mpt-"+p.item_id); if(!el)return;
    const v=r.visits||{}, pts=r.trends||[];
    let vis=""; if(v.total!=null) vis=`Visitas ML (${MP_DAYS}d): <b>${(v.total||0).toLocaleString("es-CO")}</b> · prom/día ${v.avg||0} · pico ${v.peak||0}  ·  `;
    const lvl=pts.length?Math.round(pts.reduce((a,b)=>a+b[1],0)/pts.length):0;
    const pk=pts.length?Math.max(...pts.map(x=>x[1])):0;
    el.innerHTML=`${vis}${pts.length?`Google Trends 30d: promedio <b>${lvl}/100</b> · pico ${pk} ${spark(pts)}`:"Google Trends sin respuesta"}`;
  }catch(e){ const el=document.getElementById("mpt-"+p.item_id); if(el)el.textContent="Trends no disponible"; }
}
function spark(pts){ // mini-sparkline SVG
  const vals=pts.map(x=>x[1]), mx=Math.max(...vals,1), w=160,h=26;
  const pp=vals.map((v,i)=>`${(i/(vals.length-1)*w).toFixed(1)},${(h-v/mx*h).toFixed(1)}`).join(" ");
  return `<svg width="${w}" height="${h}" style="vertical-align:middle;margin-left:8px"><polyline points="${pp}" fill="none" stroke="var(--green)" stroke-width="1.5"/></svg>`;
}
function sortMP(f){ if(MP_SORT===f)MP_DESC=!MP_DESC; else{MP_SORT=f;MP_DESC=true;} drawMP(); }
function exportMP(){
  if(!MP.length){ alert("Primero actualiza los datos."); return; }
  const cols=["item_id","title","status","category_name","price","original_price","cost","inventory","sold_total","sold_60d","net_unit","margin_pct","net_60d","restock_qty","ad_cost","ad_units","ad_sales","ad_acos","ad_roas","ad_cpc","ad_clicks","ad_prints","campaign_name","has_campaign","permalink"];
  let csv=cols.join(",")+"\n";
  MP.forEach(p=>{ csv+=cols.map(c=>{let v=p[c]==null?"":(""+p[c]).replace(/"/g,'""'); return /[",\n]/.test(v)?`"${v}"`:v;}).join(",")+"\n"; });
  const blob=new Blob([csv],{type:"text/csv"}), a=document.createElement("a");
  a.href=URL.createObjectURL(blob); a.download="BOUN_export_"+new Date().toISOString().slice(0,10)+".csv"; a.click();
}

// ── PRODUCTOS PARA COMPRAR ───────────────────────────────────────────────────
let PROD=[], PR_SORT="viability_score", PR_DESC=true, PR_Q="", PR_USER="", PR_SEL=new Set(), PR_OPEN=null;
async function renderProducts(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="row-between"><div>
      <div class="page-title">Productos para comprar</div>
      <div class="page-sub">Catálogo de productos nuevos analizados por link.</div>
    </div><button class="btn-acc" onclick="analyzeDialog()">＋ Link de nuevo producto</button></div>
    <div class="filters" style="justify-content:space-between">
      <div id="prodFilters" style="display:flex;gap:8px;flex-wrap:wrap"></div>
      <div id="prodSel" style="display:flex;gap:8px;align-items:center"></div>
    </div>
    <div id="prodBody"><div class="loading"><span class="spinner"></span> Cargando…</div></div>`;
  PR_SEL=new Set();
  try{ PROD=await api("/products"); drawPFilters(); drawProducts(); }
  catch(e){ document.getElementById("prodBody").innerHTML=`<div class="red">${e.message}</div>`; }
}
function drawPFilters(){
  const users=[...new Set(PROD.map(p=>p.created_by).filter(Boolean))].sort();
  document.getElementById("prodFilters").innerHTML=`
    <span class="muted" style="font-size:11px;align-self:center">Clic en columna: ordenar · ▸ abre el detalle</span>
    <input class="field fmini" placeholder="Buscar…" value="${esc(PR_Q)}" oninput="PR_Q=this.value;drawProducts()">
    <select class="field fmini" onchange="PR_USER=this.value;drawProducts()">
      <option value="">Ingresado por: todos</option>${users.map(u=>`<option ${PR_USER===u?"selected":""}>${esc(u)}</option>`).join("")}</select>`;
  drawPSel();
}
function drawPSel(){
  const el=document.getElementById("prodSel"); if(!el)return;
  el.innerHTML=`<span class="muted" style="font-size:12px">${PR_SEL.size} de ${PROD.length} seleccionados</span>
    <button class="btn-ghost" onclick="selAllPR(true)">Marcar todos</button>
    <button class="btn-ghost" onclick="selAllPR(false)">Desmarcar</button>
    ${isAdmin()?`<button class="btn-danger" style="${PR_SEL.size?'':'opacity:.4;pointer-events:none'}" onclick="delSelPR()">Eliminar seleccionados</button>`:""}`;
}
function selAllPR(v){ PR_SEL=v?new Set(PROD.map(p=>p.id)):new Set(); drawProducts(); }
function togglePRSel(id,ev){ ev.stopPropagation(); if(PR_SEL.has(id))PR_SEL.delete(id); else PR_SEL.add(id); drawPSel(); }
async function delSelPR(){
  if(!PR_SEL.size)return;
  if(!confirm(`¿Eliminar ${PR_SEL.size} producto(s) del catálogo?`))return;
  for(const id of PR_SEL){ try{ await api("/products/"+id,{method:"DELETE"}); }catch(e){} }
  PR_SEL=new Set(); renderProducts();
}
function drawProducts(){
  let data=PROD.filter(p=>{
    if(PR_Q && !((p.name||"").toLowerCase().includes(PR_Q.toLowerCase()) || (p.category||"").toLowerCase().includes(PR_Q.toLowerCase())))return false;
    if(PR_USER && p.created_by!==PR_USER)return false; return true;
  });
  data.sort((a,b)=>{ let x=a[PR_SORT],y=b[PR_SORT];
    if(PR_SORT==="name"||PR_SORT==="category"){x=(x||"").toLowerCase();y=(y||"").toLowerCase();return PR_DESC?(x<y?1:-1):(x>y?1:-1);}
    return PR_DESC?(y||0)-(x||0):(x||0)-(y||0); });
  drawPSel();
  if(!data.length){ document.getElementById("prodBody").innerHTML=`<div class="loading">Sin productos que coincidan.</div>`; return; }
  const cols=[["",""],["",""],["","Foto"],["name","Producto"],["category","Categoría"],
    ["viability_score","Score"],["profit_margin_pct","Margen"],["ml_monthly_sales","Ventas/mes"],
    ["sale_price","Precio"],["net_profit","Ganancia"],["created_by","Por"],["",""]];
  let html=`<table><thead><tr>${cols.map(([f,t])=>f?`<th onclick="sortPR('${f}')">${t}${PR_SORT===f?(PR_DESC?" ▼":" ▲"):""}</th>`:`<th>${t}</th>`).join("")}</tr></thead><tbody>`;
  data.forEach(p=>{
    const sc=+p.viability_score||0, scc=sc>=8?"green":sc>=5?"amber":"red";
    const mg=+p.profit_margin_pct||0, mc=mg>=20?"green":mg>=10?"amber":"red";
    const link=p.pdf_filename||""; let nm=(p.name||"").slice(0,30);
    const img=(p.image_path&&p.image_path.startsWith("http"))?`<img class="th" src="${bigImg(p.image_path)}">`:`<div class="th"></div>`;
    html+=`<tr class="mprow" onclick="togglePR(${p.id})">
      <td><span class="expand">${PR_OPEN===p.id?"▾":"▸"}</span></td>
      <td><input type="checkbox" ${PR_SEL.has(p.id)?"checked":""} onclick="togglePRSel(${p.id},event)" style="width:15px;height:15px"></td>
      <td>${img}</td>
      <td>${link.startsWith("http")?`<a href="${link}" target="_blank" onclick="event.stopPropagation()" style="color:var(--acc);text-decoration:none">${esc(nm)}</a>`:esc(nm)}<div class="pmeta">por ${esc(p.created_by||"—")}</div></td>
      <td class="muted">${esc((p.category||"").slice(0,18))}</td>
      <td class="${scc}"><b>${sc.toFixed(1)}</b></td>
      <td class="${mc}">${mg.toFixed(1)}%</td>
      <td>${(+p.ml_monthly_sales||0).toLocaleString("es-CO")}</td>
      <td>${cop(p.sale_price)}</td>
      <td class="${(+p.net_profit>=0)?'green':'red'}"><b>${cop(p.net_profit)}</b></td>
      <td class="muted" style="font-size:10px">${esc((p.created_by||"—").split("@")[0])}</td>
      <td onclick="event.stopPropagation()"><button class="btn-ghost" onclick="editCatProd(${p.id})">✏</button>${isAdmin()?` <button class="btn-danger" onclick="delCatProd(${p.id})">✕</button>`:""}</td></tr>`;
    if(PR_OPEN===p.id) html+=`<tr class="mpdetail"><td colspan="12"><div id="prd-${p.id}"><span class="spinner"></span> Cargando detalle…</div></td></tr>`;
  });
  document.getElementById("prodBody").innerHTML=html+"</tbody></table>";
  if(PR_OPEN){ const p=PROD.find(x=>x.id===PR_OPEN); if(p) fillPRDetail(p); }
}
function sortPR(f){ if(PR_SORT===f)PR_DESC=!PR_DESC; else{PR_SORT=f;PR_DESC=true;} drawProducts(); }
function togglePR(id){ PR_OPEN=PR_OPEN===id?null:id; drawProducts(); }
async function fillPRDetail(p){
  const el=document.getElementById("prd-"+p.id); if(!el)return;
  // desglose recalculado + KPIs + trends
  let breakHtml="";
  try{
    const rc=await api("/recalc",{method:"POST",body:JSON.stringify({
      sale_price:+p.sale_price||0, cost:+p.purchase_price||0, category:p.category||"Otro / General",
      commission_rate:p.ml_category_commission||0, advertising_pct:(p.advertising_pct||0)*100,
      competitor_count:p.ml_competitor_count||0, search_level:Math.round((p.ml_search_volume||0)/50) })});
    const f=rc.fees, sc=+p.viability_score||0, scc=sc>=8?"green":sc>=5?"amber":"red";
    const rows=[["Precio de venta (ML)",cop(f.sale_price),""],["Costo del producto","− "+cop(f.purchase_price),"red"],
      [`Comisión ML (${(f.commission_rate_pct||0).toFixed(0)}%)`,"− "+cop(f.commission_base),"red"],
      ["IVA sobre comisión (19%)","− "+cop(f.commission_iva),"red"],["Retención en la fuente","− "+cop(f.retencion_fuente),"red"],
      ["Costo de envío","− "+cop(f.shipping_cost),"red"],["Publicidad","− "+cop(f.advertising_cost),"red"]];
    breakHtml=`<div style="display:flex;gap:14px;margin-bottom:8px;align-items:center">
        ${p.image_path&&p.image_path.startsWith("http")?`<img src="${bigImg(p.image_path)}" style="width:60px;height:60px;border-radius:8px;object-fit:cover">`:""}
        <div class="muted" style="font-size:11px">${(p.ml_competitor_count||0).toLocaleString("es-CO")} competidores · comisión ${((p.ml_category_commission||0)*100).toFixed(0)}% · creado por ${esc(p.created_by||"—")}</div></div>
      ${rows.map(([a,b,c])=>`<div style="display:flex;justify-content:space-between;font-size:12px;padding:1px 0"><span class="muted">${a}</span><span class="${c}"><b>${b}</b></span></div>`).join("")}
      <div class="kpis" style="margin-top:8px">
        <div class="kpi"><div class="cap">Ganancia neta</div><div class="val ${f.net_profit>=0?'green':'red'}">${cop(f.net_profit)}</div></div>
        <div class="kpi"><div class="cap">Margen</div><div class="val ${f.profit_margin_pct>=20?'green':'amber'}">${(f.profit_margin_pct||0).toFixed(1)}%</div></div>
        <div class="kpi"><div class="cap">Score viabilidad</div><div class="val ${scc}">${sc.toFixed(1)}/10</div></div></div>`;
  }catch(e){ breakHtml=`<div class="red">${e.message}</div>`; }
  el.innerHTML=breakHtml+`<div class="note" id="prt-${p.id}"><span class="spinner"></span> Conectando con Google Trends…</div>`;
  try{ const t=await api(`/product-trends?title=${encodeURIComponent(p.name||"")}&days=30`); const pts=t.trends||[];
    const tl=document.getElementById("prt-"+p.id); if(tl) tl.innerHTML=pts.length?`Google Trends 30d: promedio <b>${Math.round(pts.reduce((a,b)=>a+b[1],0)/pts.length)}/100</b> ${spark(pts)}`:"Google Trends sin respuesta";
  }catch(e){}
}
async function editCatProd(pid){
  let p; try{ p=await api("/products/"+pid); }catch(e){ alert(e.message); return; }
  openModal(`<h3>Editar producto</h3><div class="sub">${esc(p.name)}</div>
    <div id="edErr" class="err"></div>
    <label class="muted" style="font-size:11px">Costo del producto</label>
    <input id="edCost" class="field" value="${Math.round(p.purchase_price||0)}" oninput="recalcEdit()">
    <label class="muted" style="font-size:11px">Precio de venta</label>
    <input id="edPrice" class="field" value="${Math.round(p.sale_price||0)}" oninput="recalcEdit()">
    <div id="edBreak"></div>
    <button class="btn-primary" onclick="saveEdit(${pid})">Guardar</button>`,true);
  window._editP=p; recalcEdit();
}
let _editFees=null;
async function recalcEdit(){
  const p=window._editP; const cost=num("edCost"), price=num("edPrice");
  if(price<=0||cost<=0){ document.getElementById("edBreak").innerHTML=""; return; }
  try{ const rc=await api("/recalc",{method:"POST",body:JSON.stringify({
      sale_price:price, cost, category:p.category||"Otro / General",
      commission_rate:p.ml_category_commission||0, advertising_pct:(p.advertising_pct||0)*100,
      competitor_count:p.ml_competitor_count||0, search_level:Math.round((p.ml_search_volume||0)/50) })});
    _editFees=rc; const f=rc.fees, sc=rc.score, scc=sc>=8?"green":sc>=5?"amber":"red";
    document.getElementById("edBreak").innerHTML=`<div style="margin:10px 0">
      <div class="kpis"><div class="kpi"><div class="cap">Ganancia neta</div><div class="val ${f.net_profit>=0?'green':'red'}">${cop(f.net_profit)}</div></div>
      <div class="kpi"><div class="cap">Margen</div><div class="val ${f.profit_margin_pct>=20?'green':'amber'}">${(f.profit_margin_pct||0).toFixed(1)}%</div></div>
      <div class="kpi"><div class="cap">Score</div><div class="val ${scc}">${sc.toFixed(1)}/10</div></div></div></div>`;
  }catch(e){}
}
async function saveEdit(pid){
  const cost=num("edCost"),price=num("edPrice"),f=_editFees?_editFees.fees:null;
  if(price<=0||cost<=0){ document.getElementById("edErr").textContent="Precio y costo válidos."; return; }
  const body={purchase_price:cost, sale_price:price,
    shipping_cost:_editFees?_editFees.shipping:0, ml_commission_total:f?f.commission_total:0,
    total_costs:f?f.total_costs:0, net_profit:f?f.net_profit:0,
    profit_margin_pct:f?f.profit_margin_pct:0, viability_score:_editFees?_editFees.score:0};
  try{ await api("/products/"+pid,{method:"PATCH",body:JSON.stringify(body)}); closeModal(); renderProducts(); }
  catch(e){ document.getElementById("edErr").textContent=e.message; }
}
async function delCatProd(pid){ if(!confirm("¿Eliminar producto del catálogo?"))return;
  try{ await api("/products/"+pid,{method:"DELETE"}); renderProducts(); }catch(e){ alert(e.message); } }

let ANA=null;
function analyzeDialog(){
  ANA=null;
  openModal(`<h3>Link de nuevo producto</h3>
    <div class="sub">Pega el link de la publicación de MercadoLibre y el costo.</div>
    <div id="anaErr" class="err"></div>
    <input id="anaUrl" class="field" placeholder="Link de la publicación de MercadoLibre">
    <input id="anaCost" class="field" placeholder="Costo del producto (COP)">
    <button class="btn-primary" onclick="doAnalyze()">Analizar publicación</button>
    <div id="anaRes"></div>`,true);
}
async function doAnalyze(){
  const url=val("anaUrl"),cost=num("anaCost");
  const err=document.getElementById("anaErr"); err.textContent="";
  if(!url){ err.textContent="Pega el link."; return; }
  document.getElementById("anaRes").innerHTML=`<div class="loading"><span class="spinner"></span> Analizando en MercadoLibre…</div>`;
  try{ const r=await api("/analyze",{method:"POST",body:JSON.stringify({url,cost})});
    ANA=r; showAnaResult(r,cost);
  }catch(e){ document.getElementById("anaRes").innerHTML=""; err.textContent=e.message; }
}
function showAnaResult(r,cost){
  const price=r.real_price||0;
  document.getElementById("anaRes").innerHTML=`
    <div style="display:flex;gap:12px;margin:14px 0;align-items:center">
      ${r.image_url?`<img src="${bigImg(r.image_url)}" style="width:72px;height:72px;border-radius:8px;object-fit:cover">`:""}
      <div><div style="font-weight:700">${esc(r.product_name||"")}</div>
        <div class="muted" style="font-size:11px">${(r.same_product_listings||0)} publicaciones del mismo producto · ${(r.competitor_count||0).toLocaleString("es-CO")} competidores · ${r.commission_is_real?"comisión real":"comisión estimada"} ${((r.commission_rate||0)*100).toFixed(0)}%</div></div>
    </div>
    <label class="muted" style="font-size:11px">Precio de venta en ML ${r.price_unavailable?"(⚠ ML no lo expone — escríbelo)":"(editable)"}</label>
    <input id="anaPrice" class="field" value="${price||""}" placeholder="Precio de venta" oninput="recalcAna(${cost})">
    <div id="anaBreak"></div>
    <div id="anaTrends" class="note"><span class="spinner"></span> Conectando con Google Trends…</div>
    <button class="btn-primary" onclick="saveAnalyzed(${cost})">Guardar producto</button>`;
  if(price>0) recalcAna(cost);
  // Trends
  api(`/product-trends?title=${encodeURIComponent(r.product_name||"")}&days=30`).then(t=>{
    const el=document.getElementById("anaTrends"); if(!el)return; const pts=t.trends||[];
    if(pts.length){ const lvl=Math.round(pts.reduce((a,b)=>a+b[1],0)/pts.length), pk=Math.max(...pts.map(x=>x[1]));
      ANA._lvl=lvl; el.innerHTML=`Google Trends 30d: promedio <b>${lvl}/100</b> · pico ${pk} ${spark(pts)}`; recalcAna(cost);
    } else el.textContent="Google Trends sin respuesta";
  }).catch(()=>{});
}
let ANA_FEES=null;
async function recalcAna(cost){
  const price=num("anaPrice"); if(price<=0)return; const r=ANA;
  try{ const rc=await api("/recalc",{method:"POST",body:JSON.stringify({
      sale_price:price, cost, category:r.category_id||"Otro / General",
      commission_rate:r.commission_rate||0, advertising_pct:r.advertising_pct||0,
      competitor_count:r.competitor_count||0, search_level:ANA._lvl||r.search_level||0 })});
    ANA_FEES=rc; const f=rc.fees;
    const rows=[["Precio de venta (ML)",cop(f.sale_price),""],["Costo del producto","− "+cop(f.purchase_price),"red"],
      [`Comisión ML (${(f.commission_rate_pct||0).toFixed(0)}%)`,"− "+cop(f.commission_base),"red"],
      ["IVA sobre comisión (19%)","− "+cop(f.commission_iva),"red"],["Retención en la fuente","− "+cop(f.retencion_fuente),"red"],
      ["Costo de envío","− "+cop(f.shipping_cost),"red"],["Publicidad","− "+cop(f.advertising_cost),"red"]];
    const sc=rc.score||0, scc=sc>=8?"green":sc>=5?"amber":"red";
    document.getElementById("anaBreak").innerHTML=`<div style="margin:12px 0">
      ${rows.map(([a,b,c])=>`<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0"><span class="muted">${a}</span><span class="${c}"><b>${b}</b></span></div>`).join("")}
      <div class="kpis" style="margin-top:10px">
        <div class="kpi"><div class="cap">Ganancia neta</div><div class="val ${f.net_profit>=0?'green':'red'}">${cop(f.net_profit)}</div></div>
        <div class="kpi"><div class="cap">Margen</div><div class="val ${f.profit_margin_pct>=20?'green':'amber'}">${(f.profit_margin_pct||0).toFixed(1)}%</div></div>
        <div class="kpi"><div class="cap">Score viabilidad</div><div class="val ${scc}">${sc.toFixed(1)}/10</div></div>
      </div></div>`;
  }catch(e){}
}
async function saveAnalyzed(cost){
  const price=num("anaPrice"); const r=ANA, f=ANA_FEES?ANA_FEES.fees:null;
  if(price<=0||cost<=0){ alert("Precio y costo deben ser válidos."); return; }
  const body={ name:r.product_name||"Producto ML", category:r.category_id||"Otro / General",
    purchase_price:cost, sale_price:price, ml_competitor_count:r.competitor_count||0,
    ml_category_commission:r.commission_rate||0, ml_monthly_sales:(ANA._lvl||0)*5, ml_search_volume:(ANA._lvl||0)*50,
    shipping_cost:(ANA_FEES?ANA_FEES.shipping:r.shipping_cost)||0, advertising_pct:(r.advertising_pct||0)/100,
    ml_commission_total:f?f.commission_total:0, total_costs:f?f.total_costs:0,
    viability_score:ANA_FEES?ANA_FEES.score:0, profit_margin_pct:f?f.profit_margin_pct:0, net_profit:f?f.net_profit:0,
    permalink:r.permalink||"", image_url:r.image_url||"" };
  try{ await api("/products",{method:"POST",body:JSON.stringify(body)}); closeModal(); go("products"); }
  catch(e){ alert(e.message); }
}

// ── CONFIGURACIÓN ────────────────────────────────────────────────────────────
async function renderSettings(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="page-title">Configuración</div>
    <div class="page-sub">Personaliza la aplicación para tu empresa.</div>
    <div id="setBody"><div class="loading"><span class="spinner"></span> Cargando…</div></div>`;
  try{
    const st=await api("/ml-status"); const cf=await api("/settings");
    const adm=isAdmin(), ro=adm?"":"disabled";
    let aps=null; if(adm){ try{ aps=await api("/sync/apply-status"); }catch(e){} }
    document.getElementById("setBody").innerHTML=`
      <div class="set-sec">INFORMACIÓN DE LA EMPRESA</div>
      <div class="set-grid">
        ${setField("Nombre de empresa","s_name",cf.company_name,ro)}
        ${setField("NIT / RUT","s_nit",cf.company_nit,ro)}
        ${setField("Usuario por defecto","s_user",cf.default_user,ro)}
        ${setField("Moneda principal","s_curr",cf.currency,ro)}
      </div>
      ${adm?`<button class="btn-acc" style="margin-top:10px" onclick="saveCompany()">Guardar información</button>`:`<div class="muted" style="font-size:11px">Solo el administrador puede editar la información de la empresa.</div>`}

      <div class="set-sec" style="margin-top:24px">MERCADOLIBRE API</div>
      <div class="muted" style="font-size:12px;margin-bottom:8px">Conecta tu cuenta de MercadoLibre para datos reales: precios, ventas, competidores y envíos. La conexión se comparte con todo el equipo por la nube.</div>
      <div style="font-size:14px;margin-bottom:10px">${st.connected
        ? `<span class="green">● Conectado${st.username?" como <b>"+esc(st.username)+"</b>":""}</span>`
        : `<span class="red">○ No conectado</span>`}</div>
      ${adm?`<div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn-acc" onclick="mlConnect()">Conectar con MercadoLibre</button>
        ${st.connected?`<button class="btn-ghost" onclick="mlDisconnect()">Desconectar</button>`:""}
        <button class="btn-ghost" onclick="mlAdvanced(${cf.has_secret})">Configuración avanzada (APP ID y Secret)</button>
      </div>`:`<div class="muted" style="font-size:11px">La conexión la administra el administrador.</div>`}

      ${adm&&aps?syncApplyHTML(aps):""}

      ${adm?scanHTML():""}

      ${adm?combosHTML():""}

      <div class="set-sec" style="margin-top:24px">TU CUENTA</div>
      <div style="font-size:13px">Usuario: <b>${esc(USER.username)}</b> · ${adm?"Administrador":"Colaborador"}</div>
      <button class="btn-ghost" style="margin-top:10px" onclick="changePwDialog()">Cambiar mi contraseña</button>

      <div class="set-sec" style="margin-top:24px">ACERCA DE</div>
      <div class="inv-card" style="padding:16px;max-width:600px">
        <div style="font-weight:700">BOUN · Análisis MercadoLibre — Web</div>
        <div class="muted" style="font-size:12px;margin-top:6px">Herramienta de análisis de rentabilidad para vendedores en MercadoLibre Colombia. Calcula comisiones, impuestos, margen de ganancia y score de viabilidad.</div>
        <div class="muted" style="font-size:11px;margin-top:6px">Comisiones ML 2024 · Retención en fuente: 2.8% · IVA comisión: 19%</div>
      </div>`;
    if(adm) scanInit();   // reconecta el progreso si ya hay un escaneo en curso
    if(adm) combosInit(); // carga los combos definidos
  }catch(e){ document.getElementById("setBody").innerHTML=`<div class="red">${e.message}</div>`; }
}
function setField(label,id,val,ro){
  return `<div class="set-row"><label>${label}</label><input id="${id}" class="field" style="margin:0" value="${esc(val||"")}" ${ro}></div>`;
}
async function saveCompany(){
  try{ await api("/settings",{method:"POST",body:JSON.stringify({
    company_name:val("s_name"),company_nit:val("s_nit"),default_user:val("s_user"),currency:val("s_curr")})});
    alert("Información guardada.");
  }catch(e){ alert(e.message); }
}
function syncApplyHTML(aps){
  const ch=aps.channels||[], dry=aps.dry_run, md=aps.max_delta;
  const mlOn=ch.includes("mercadolibre");
  const estado = dry
    ? `<span class="green">● DRY-RUN — calcula el plan pero NO escribe en ningún canal</span>`
    : `<span class="red">● ESCRIBIENDO en: <b>${esc(ch.join(", "))}</b></span>`;
  return `<div class="set-sec" style="margin-top:24px">SINCRONIZACIÓN DE STOCK · ESCRITURA REAL</div>
    <div class="muted" style="font-size:12px;margin-bottom:8px">Controla si el motor de sincronización escribe stock real en los canales tras cada venta. En DRY-RUN solo calcula el reparto (seguro). Activa un canal a la vez y vigila la auditoría antes de ampliar.</div>
    <div class="inv-card" style="padding:16px;max-width:600px">
      <div style="font-size:14px;margin-bottom:10px">${estado}</div>
      <div class="set-row" style="max-width:340px"><label>Tope de salto por publicación (max_delta)</label>
        <input id="s_maxdelta" class="field" style="margin:0" type="number" min="0" value="${md==null?"":md}" placeholder="vacío = sin tope"></div>
      <div class="muted" style="font-size:11px;margin:6px 0 12px">Si el nuevo valor difiere del actual en más de este tope, NO escribe (red anti-cálculo-raro). Recomendado para estrenar: 5.</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        ${mlOn
          ? `<button class="btn-ghost" onclick="syncApplyKill()">⏸ Pausar todo (DRY-RUN)</button>`
          : `<button class="btn-acc" onclick="syncApplyEnableML()">▶ Activar escritura en MercadoLibre</button>`}
        <button class="btn-ghost" onclick="syncApplySaveDelta()">Guardar tope</button>
      </div>
    </div>`;
}
async function syncApplyEnableML(){
  const md=val("s_maxdelta");
  if(!confirm("Vas a ACTIVAR la escritura real de stock en MercadoLibre. A partir de ahora, cada venta procesada ajustará el available_quantity de tus publicaciones ML.\n\n¿Confirmas? (puedes pausarlo en 1 clic en cualquier momento)"))return;
  try{
    const body={channels:["mercadolibre"]};
    if(md!=="") body.max_delta=parseInt(md,10);
    await api("/sync/apply-config",{method:"POST",body:JSON.stringify(body)});
    alert("✓ Escritura activada en MercadoLibre.");
    renderSettings();
  }catch(e){ alert(e.message); }
}
async function syncApplyKill(){
  if(!confirm("¿Pausar la escritura real en TODOS los canales? El motor vuelve a DRY-RUN (solo calcula, no escribe). El inventario central y la cola de bodega siguen funcionando."))return;
  try{
    await api("/sync/apply-config",{method:"POST",body:JSON.stringify({channels:[]})});
    alert("✓ En DRY-RUN. Ningún canal escribe.");
    renderSettings();
  }catch(e){ alert(e.message); }
}
async function syncApplySaveDelta(){
  const md=val("s_maxdelta");
  try{
    await api("/sync/apply-config",{method:"POST",body:JSON.stringify({max_delta:md===""?0:parseInt(md,10)})});
    alert("✓ Tope guardado.");
    renderSettings();
  }catch(e){ alert(e.message); }
}

// ── Escaneo de reconciliación de stock (Web BOUN → canales) ─────────────────
const SCAN_CH = {mercadolibre:"MercadoLibre", falabella:"Falabella",
                 shopify_boun:"Shopify BOUN", shopify_kat:"Shopify KAT"};
function scanChLabel(c){ return SCAN_CH[c] || c; }
function scanHTML(){
  return `<div class="set-sec" style="margin-top:24px">ESCANEO DE RECONCILIACIÓN DE STOCK</div>
    <div class="muted" style="font-size:12px;margin-bottom:8px">Recorre <b>todas</b> las publicaciones de los canales elegidos y las iguala al disponible real de tu inventario (Bogotá + Yopal − pendientes). Corrige agotadas y desfases <b>sin importar el tamaño del salto</b>. Salta <b>Full y catálogo</b> automáticamente. Empieza siempre con <b>Previsualizar</b> (no escribe nada).</div>
    <div class="inv-card" style="padding:16px;max-width:680px">
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px">
        ${Object.keys(SCAN_CH).map(c=>`<label style="font-size:13px;display:flex;gap:6px;align-items:center;cursor:pointer"><input type="checkbox" class="scanch" value="${c}" checked> ${SCAN_CH[c]}</label>`).join("")}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button type="button" id="scanPrevBtn" class="btn-acc" onclick="scanStart('preview')">🔍 Previsualizar escaneo</button>
        <button type="button" id="scanApplyBtn" class="btn-ghost" onclick="scanStart('apply')">✍ Aplicar correcciones</button>
      </div>
      <div id="scanOut" style="margin-top:14px"></div>
      <div style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px">
        <label style="font-size:13px;display:flex;gap:8px;align-items:center;cursor:pointer;margin-bottom:10px;padding:8px 10px;border:1px solid var(--amber);border-radius:8px;background:rgba(224,162,60,.08)">
          <input type="checkbox" id="mlSoloBogota" onchange="scanDailySave()"> <span class="amber" style="font-weight:700">⏳ Regla temporal:</span> MercadoLibre vende solo bodega Bogotá <span class="muted" style="font-size:11px">(Yopal no cuenta para ML; los demás canales usan ambas)</span>
        </label>
        <label style="font-size:13px;display:flex;gap:8px;align-items:center;cursor:pointer;margin-bottom:10px">
          <input type="checkbox" id="scanReactivate" onchange="scanDailySave()"> Reactivar publicaciones agotadas <span class="muted" style="font-size:11px">(ML pausadas por falta de stock → vuelven a activas con stock)</span>
        </label>
        <label style="font-size:13px;display:flex;gap:8px;align-items:center;cursor:pointer">
          <input type="checkbox" id="scanDaily" onchange="scanDailySave()"> Escaneo diario automático <span class="muted" style="font-size:11px">(aplica solo, todos los días)</span>
        </label>
        <div style="font-size:12px;color:var(--muted);margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          a las <input id="scanDailyHour" type="number" min="0" max="23" value="4" onchange="scanDailySave()" style="width:56px;height:30px;background:var(--surf);color:var(--text);border:1px solid var(--border);border-radius:6px;text-align:center;font-size:13px"> h (hora Colombia)
          <span id="scanDailyMsg" style="font-size:11px"></span>
        </div>
      </div>
    </div>`;
}
async function scanInit(){
  // Al abrir Configuración: si ya hay un escaneo corriendo, reengancha el
  // progreso en vez de mostrar los botones como si nada; si el último terminó,
  // muestra su resumen para no perderlo. Y refleja el estado del escaneo diario.
  try{
    const aps=await api("/sync/apply-status");
    const cb=document.getElementById("scanDaily"); if(cb) cb.checked=!!aps.scan_daily;
    const hr=document.getElementById("scanDailyHour"); if(hr && aps.scan_daily_hour!=null) hr.value=aps.scan_daily_hour;
    const rc=document.getElementById("scanReactivate"); if(rc) rc.checked=aps.scan_reactivate!==false;
    const mb=document.getElementById("mlSoloBogota"); if(mb) mb.checked=!!aps.ml_solo_bogota;
  }catch(e){}
  const out=document.getElementById("scanOut");
  if(!out) return;
  let s; try{ s=await api("/sync/scan-status"); }catch(e){ return; }
  if(s.status==="running") scanPoll();
  else if(s.status==="done" && s.counts && s.rows_total) out.innerHTML=scanResultHTML(s);
}
async function scanDailySave(){
  const en=document.getElementById("scanDaily").checked;
  const rc=document.getElementById("scanReactivate").checked;
  const mb=document.getElementById("mlSoloBogota").checked;
  let h=parseInt(document.getElementById("scanDailyHour").value,10); if(isNaN(h))h=4;
  const msg=document.getElementById("scanDailyMsg");
  try{
    await api("/sync/apply-config",{method:"POST",body:JSON.stringify({scan_daily:en,scan_daily_hour:h,scan_reactivate:rc,ml_solo_bogota:mb})});
    if(msg){ msg.textContent="✓ guardado"; msg.className="green"; setTimeout(()=>{if(msg)msg.textContent="";},2000); }
  }catch(e){ if(msg){ msg.textContent=e.message; msg.className="red"; } }
}
let SCAN_ACTIVE=false;   // hay un escaneo iniciado por este usuario en curso
function scanLoadingHTML(txt){
  return `<div class="loading" style="padding:22px;text-align:center;border:1px solid var(--border);border-radius:8px;background:var(--surf)">
      <span class="spinner" style="width:22px;height:22px;border-width:3px"></span>
      <div style="margin-top:10px;font-size:14px;color:var(--text);font-weight:700">${txt}</div>
      <div style="margin-top:4px;font-size:11px;color:var(--muted)">Recorre todas las publicaciones de los canales · puede tardar 1–3 minutos</div>
    </div>`;
}
async function scanStart(mode){
  const chans=[...document.querySelectorAll(".scanch:checked")].map(e=>e.value);
  if(!chans.length){ alert("Elige al menos un canal."); return; }
  if(mode==="apply" && !confirm("Vas a ESCRIBIR stock real en: "+chans.map(scanChLabel).join(", ")+".\n\nCada publicación (excepto Full y catálogo) quedará igualada al disponible de tu inventario, SIN tope de salto. Esto corrige agotadas y desfases, y reactiva las agotadas.\n\n¿Confirmas?")) return;
  SCAN_ACTIVE=true;
  scanSetBusy(true);
  const out=document.getElementById("scanOut");
  if(out) out.innerHTML=scanLoadingHTML(mode==="apply"?"Iniciando y aplicando…":"Iniciando escaneo…");
  try{
    await api("/sync/scan-start",{method:"POST",body:JSON.stringify({mode,channels:chans})});
    scanPoll();
  }catch(e){
    // 409 = ya hay un escaneo en curso → engancha su progreso en vez de solo el error.
    if(/curso/i.test(e.message||"")){ scanPoll(); }
    else { SCAN_ACTIVE=false; scanSetBusy(false); if(out) out.innerHTML=`<div class="red" style="font-size:12px">${esc(e.message)}</div>`; }
  }
}
function scanSetBusy(busy){
  // Desactiva/activa los botones de escaneo mientras hay uno en curso.
  ["scanPrevBtn","scanApplyBtn"].forEach(id=>{
    const b=document.getElementById(id);
    if(b){ b.disabled=busy; b.style.opacity=busy?"0.5":""; b.style.cursor=busy?"not-allowed":""; }
  });
}
function scanBar(done,total,mode){
  const pct=total?Math.round((done||0)/total*100):0;
  const verbo = mode==="apply" ? "Aplicando" : "Escaneando";
  return `<div style="padding:16px;border:1px solid var(--border);border-radius:8px;background:var(--surf)">
      <div style="font-size:13px;color:var(--text);margin-bottom:8px;font-weight:600"><span class="spinner"></span> ${verbo}… <b>${done||0}/${total||0}</b> productos · ${pct}%</div>
      <div style="height:11px;background:var(--bg);border:1px solid var(--border);border-radius:6px;overflow:hidden">
        <div style="height:100%;width:${pct}%;background:var(--acc);border-radius:6px;transition:width .35s ease"></div>
      </div>
      <div style="margin-top:6px;font-size:11px;color:var(--muted)">No cierres esta sección; al terminar verás el reporte aquí mismo.</div>
    </div>`;
}
async function scanPoll(){
  let s; try{ s=await api("/sync/scan-status"); }
  catch(e){ SCAN_ACTIVE=false; scanSetBusy(false); const o=document.getElementById("scanOut"); if(o) o.innerHTML=`<div class="red" style="font-size:12px">${esc(e.message)}</div>`; return; }
  // Releemos el contenedor en CADA tick: si Configuración se re-renderizó, el
  // <div id="scanOut"> es otro nodo. No cortamos la cadena si está null (el
  // escaneo sigue en el servidor); seguimos sondeando y pintamos cuando reaparezca.
  const out=document.getElementById("scanOut");
  if(s.status==="running"){
    SCAN_ACTIVE=true; scanSetBusy(true);
    if(out) out.innerHTML=scanBar(s.done,s.total,s.mode);
    setTimeout(scanPoll,3000); return;
  }
  // El thread del servidor tarda un instante en marcar "running" tras arrancar:
  // si lo acabamos de iniciar y aún figura idle, seguimos mostrando la carga.
  if(s.status==="idle" && SCAN_ACTIVE){
    if(out) out.innerHTML=scanLoadingHTML("Iniciando escaneo…");
    setTimeout(scanPoll,2000); return;
  }
  SCAN_ACTIVE=false; scanSetBusy(false);
  if(!out) return;
  if(s.status==="error"){ out.innerHTML=`<div class="red" style="font-size:12px">Error: ${esc(s.error||"")}</div>`; return; }
  if(s.status==="idle"){ out.innerHTML=""; return; }
  out.innerHTML=scanResultHTML(s);
}
function scanResultHTML(s){
  const c=s.counts||{}, dry=s.mode!=="apply";
  const rows=(s.rows||[]).filter(r=>r.accion!=="sin_cambio");
  const head=`<div style="font-size:13px;margin-bottom:10px">
      <span class="${dry?"amber":"green"}">●</span> <b>${dry?"Previsualización":"Cambios aplicados"}</b> · ${esc((s.channels||[]).map(scanChLabel).join(", "))}<br>
      <span style="font-size:12px">${dry?"Cambiarían":"Escritas"}: <b class="green">${c.cambios||0}</b>${(c.reactivadas||0)?` · <b style="color:var(--blue)">${dry?"Reactivaría":"Reactivadas"}: ${c.reactivadas}</b>`:""} · Ya alineadas: ${c.sin_cambio||0} · Saltadas (Full/catálogo): ${c.saltados||0} · Errores: <span class="${(c.errores||0)?"red":""}">${c.errores||0}</span></span></div>`;
  if(!rows.length) return head+`<div class="muted" style="font-size:12px">Todo está alineado con tu inventario. No hay cambios que mostrar.</div>`;
  const trs=rows.slice(0,500).map(r=>{
    const col=r.accion.startsWith("saltado")?"var(--dim)":r.accion==="error"?"var(--red)":r.accion.startsWith("reactiv")?"var(--blue)":"var(--green)";
    const arrow=(r.actual!=null&&r.objetivo!=null)?`${r.actual} → <b>${r.objetivo}</b>`:(r.objetivo!=null?`<b>${r.objetivo}</b>`:"—");
    return `<tr>
      <td style="padding:4px 8px"><span class="code-chip" style="font-size:10px">${esc(r.codigo||"")}</span></td>
      <td style="padding:4px 8px">${esc(scanChLabel(r.canal))}</td>
      <td style="padding:4px 8px;color:var(--dim);font-size:10px">${esc(r.ref||"")}</td>
      <td style="padding:4px 8px;text-align:right;white-space:nowrap">${arrow}</td>
      <td style="padding:4px 8px;color:${col};white-space:nowrap">${esc(r.accion)}</td></tr>`;
  }).join("");
  return head+`<div style="max-height:360px;overflow:auto;border:1px solid var(--border);border-radius:8px">
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead><tr style="position:sticky;top:0;background:var(--surf)">
          <th style="padding:6px 8px;text-align:left">Código</th>
          <th style="padding:6px 8px;text-align:left">Canal</th>
          <th style="padding:6px 8px;text-align:left">Publicación</th>
          <th style="padding:6px 8px;text-align:right">Actual → Objetivo</th>
          <th style="padding:6px 8px;text-align:left">Acción</th></tr></thead>
        <tbody>${trs}</tbody></table></div>
      ${rows.length>500?`<div class="muted" style="font-size:11px;margin-top:6px">Mostrando 500 de ${rows.length} filas.</div>`:""}
      ${dry&&(c.cambios||0)?`<button type="button" class="btn-acc" style="margin-top:12px" onclick="scanStart('apply')">✍ Aplicar estas ${c.cambios} correcciones</button>`:""}`;
}
// ── Combos (kits) ───────────────────────────────────────────────────────────
let COMBOS={};                       // {codigo_combo: [{codigo,cant}, …]}
let COMBO_DRAFT=[{codigo:"",cant:1}];// componentes del combo en edición
let COMBO_PRODUCTS=[];               // [{code,name,thumb}] para los buscadores
let COMBO_CODE="";                   // código del combo seleccionado en el form
function prodName(code){ const p=COMBO_PRODUCTS.find(x=>x.code===code); return p?p.name:""; }
// Buscador desplegable de producto con foto. id único por campo.
function pickInput(id, code, ph){
  const nm=code?(esc(code)+" — "+esc(prodName(code))):"";
  return `<div style="position:relative;flex:1">
    <input id="${id}" class="field" style="margin:0;width:100%" autocomplete="off" placeholder="${ph}" value="${nm}"
      oninput="pickFilter('${id}',this.value)" onfocus="pickFilter('${id}',this.value)" onblur="pickBlur('${id}')">
    <div id="${id}-drop" style="display:none;position:absolute;left:0;right:0;top:44px;z-index:30;max-height:260px;overflow:auto;background:var(--surf);border:1px solid var(--border);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.45)"></div>
  </div>`;
}
function pickFilter(id, q){
  const drop=document.getElementById(id+"-drop"); if(!drop) return;
  q=(q||"").toLowerCase().trim();
  let list=COMBO_PRODUCTS;
  if(q) list=list.filter(p=>((p.code||"")+" "+(p.name||"")).toLowerCase().includes(q));
  list=list.slice(0,20);
  if(!list.length){ drop.innerHTML='<div style="padding:8px;font-size:12px;color:var(--muted)">Sin resultados</div>'; drop.style.display="block"; return; }
  drop.innerHTML=list.map(p=>{
    const img=p.thumb?`<img src="${esc(p.thumb)}" style="width:36px;height:36px;border-radius:5px;object-fit:cover;flex:0 0 auto">`:`<div style="width:36px;height:36px;border-radius:5px;background:var(--bg);flex:0 0 auto"></div>`;
    return `<div onmousedown="pickChoose('${id}','${esc(p.code)}')" style="display:flex;align-items:center;gap:8px;padding:6px 8px;cursor:pointer;border-bottom:1px solid var(--border)" onmouseover="this.style.background='var(--hov)'" onmouseout="this.style.background=''">
      ${img}<span class="code-chip" style="font-size:10px">${esc(p.code)}</span><span style="font-size:12px;flex:1">${esc(p.name)}</span></div>`;
  }).join("");
  drop.style.display="block";
}
function pickChoose(id, code){
  if(id==="pkComboCode"){ COMBO_CODE=code; }
  else if(id.indexOf("pkComp-")===0){ const i=parseInt(id.split("-")[1],10); if(COMBO_DRAFT[i]) COMBO_DRAFT[i].codigo=code; }
  const inp=document.getElementById(id); if(inp) inp.value=code+" — "+prodName(code);
  const drop=document.getElementById(id+"-drop"); if(drop) drop.style.display="none";
}
function pickBlur(id){
  setTimeout(()=>{
    const d=document.getElementById(id+"-drop"); if(d) d.style.display="none";
    const inp=document.getElementById(id); if(!inp) return;
    let code = id==="pkComboCode" ? COMBO_CODE
      : (id.indexOf("pkComp-")===0 ? ((COMBO_DRAFT[parseInt(id.split("-")[1],10)]||{}).codigo||"") : "");
    inp.value = code ? (code+" — "+prodName(code)) : "";   // restaura el elegido
  },150);
}
function combosHTML(){
  return `<div class="set-sec" style="margin-top:24px">COMBOS (KITS)</div>
    <div class="muted" style="font-size:12px;margin-bottom:8px">Define combos: al vender un combo, el sistema <b>descuenta del inventario los productos que lo componen</b>. El stock del combo se calcula solo (cuántos puedes armar). El producto-combo debe existir en tu inventario con sus publicaciones asignadas.</div>
    <div class="inv-card" style="padding:16px;max-width:680px;overflow:visible">
      <div id="combosList"></div>
      <div id="combosForm"></div>
    </div>`;
}
async function combosInit(){
  if(!document.getElementById("combosList")) return;
  try{ const r=await api("/combos"); COMBOS=r.combos||{}; }catch(e){ COMBOS={}; }
  try{ const inv=await api("/inventory"); COMBO_PRODUCTS=(inv||[]).map(p=>({code:p.code,name:p.name,thumb:p.thumb})); }catch(e){ COMBO_PRODUCTS=[]; }
  COMBO_DRAFT=[{codigo:"",cant:1}]; COMBO_CODE="";
  combosRenderList(); combosRenderForm();
}
function combosRenderList(){
  const el=document.getElementById("combosList"); if(!el) return;
  const keys=Object.keys(COMBOS);
  if(!keys.length){ el.innerHTML='<div class="muted" style="font-size:12px;margin-bottom:6px">No hay combos definidos todavía.</div>'; return; }
  el.innerHTML=keys.map(k=>{
    const comps=(COMBOS[k]||[]).map(c=>`<span class="sku" style="margin:0 4px 2px 0;display:inline-block">${esc(c.codigo)} ×${c.cant}</span>`).join("");
    return `<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border)">
      <span class="code-chip">${esc(k)}</span>
      <span style="flex:1;font-size:12px">= ${comps}</span>
      <button type="button" class="btn-danger" onclick="combosEdit('${esc(k)}')" style="margin-right:4px">Editar</button>
      <button type="button" class="btn-danger" onclick="combosDelete('${esc(k)}')">✕</button>
    </div>`;
  }).join("");
}
function combosRenderForm(){
  const el=document.getElementById("combosForm"); if(!el) return;
  el.innerHTML=`<div style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px">
    <div style="font-size:13px;font-weight:600;margin-bottom:8px">Agregar / editar combo</div>
    <div class="set-row" style="margin-bottom:10px;align-items:flex-start"><label style="width:150px;padding-top:10px">Producto-combo</label>
      ${pickInput("pkComboCode", COMBO_CODE, "Buscar combo por código o nombre…")}</div>
    <div style="font-size:12px;color:var(--muted);margin-bottom:6px">Componentes (producto + cuántas unidades lleva el combo):</div>
    <div id="comboComps"></div>
    <button type="button" class="btn-ghost" style="margin-top:6px" onclick="comboDraftAdd()">+ Agregar componente</button>
    <div style="margin-top:12px"><button type="button" class="btn-acc" onclick="combosSaveDraft()">Guardar combo</button>
      <span id="combosMsg" style="font-size:11px;margin-left:8px"></span></div>
  </div>`;
  comboCompsRender();
}
function comboCompsRender(){
  const el=document.getElementById("comboComps"); if(!el) return;
  el.innerHTML=COMBO_DRAFT.map((c,i)=>`<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
      ${pickInput("pkComp-"+i, c.codigo, "Buscar producto componente…")}
      <input class="field" style="margin:0;width:72px;flex:0 0 auto" type="number" min="1" value="${c.cant}" oninput="COMBO_DRAFT[${i}].cant=parseInt(this.value)||1" title="unidades por combo">
      <button type="button" class="btn-ghost" style="flex:0 0 auto" onclick="comboDraftDel(${i})">✕</button>
    </div>`).join("");
}
function comboDraftAdd(){ COMBO_DRAFT.push({codigo:"",cant:1}); comboCompsRender(); }
function comboDraftDel(i){ COMBO_DRAFT.splice(i,1); if(!COMBO_DRAFT.length)COMBO_DRAFT.push({codigo:"",cant:1}); comboCompsRender(); }
function combosEdit(code){
  COMBO_CODE=code;
  COMBO_DRAFT=(COMBOS[code]||[]).map(c=>({codigo:c.codigo,cant:c.cant}));
  if(!COMBO_DRAFT.length)COMBO_DRAFT=[{codigo:"",cant:1}];
  combosRenderForm();
}
async function combosSaveDraft(){
  const code=(COMBO_CODE||"").trim();
  const comps=COMBO_DRAFT.map(c=>({codigo:(c.codigo||"").trim(),cant:parseInt(c.cant)||1})).filter(c=>c.codigo);
  const msg=document.getElementById("combosMsg");
  if(!code){ if(msg){msg.textContent="Elige el producto-combo"; msg.className="red";} return; }
  if(!comps.length){ if(msg){msg.textContent="Agrega al menos un componente"; msg.className="red";} return; }
  COMBOS[code]=comps;
  try{
    const r=await api("/combos",{method:"POST",body:JSON.stringify({combos:COMBOS})});
    COMBOS=r.combos||COMBOS;
    if(msg){msg.textContent="✓ guardado"; msg.className="green"; setTimeout(()=>{if(msg)msg.textContent="";},2000);}
    COMBO_CODE=""; COMBO_DRAFT=[{codigo:"",cant:1}];
    combosRenderList(); combosRenderForm();
  }catch(e){ if(msg){msg.textContent=e.message; msg.className="red";} }
}
async function combosDelete(code){
  if(!confirm("¿Eliminar el combo "+code+"? (no borra el producto, solo su definición de componentes)")) return;
  delete COMBOS[code];
  try{ const r=await api("/combos",{method:"POST",body:JSON.stringify({combos:COMBOS})}); COMBOS=r.combos||{}; combosRenderList(); }
  catch(e){ alert(e.message); }
}
async function mlConnect(){
  try{ const r=await api("/ml/auth-url");
    openModal(`<h3>Conectar con MercadoLibre</h3>
      <div class="sub">1. Abre el enlace, inicia sesión en MercadoLibre y autoriza BOUN.<br>2. Te redirigirá a una página (puede mostrar 404, es normal).<br>3. Copia la URL completa de la barra del navegador y pégala abajo.</div>
      <a href="${r.url}" target="_blank" class="btn-acc" style="display:inline-block;text-decoration:none;line-height:40px;margin-bottom:10px">Abrir MercadoLibre →</a>
      <div id="mlErr" class="err"></div>
      <input id="mlCode" class="field" placeholder="Pega aquí la URL completa o el código">
      <button class="btn-primary" onclick="mlExchange()">Conectar</button>`);
  }catch(e){ alert(e.message); }
}
async function mlExchange(){
  const code=val("mlCode"); const err=document.getElementById("mlErr"); err.textContent="";
  if(!code){ err.textContent="Pega la URL o el código."; return; }
  err.innerHTML='<span class="spinner"></span> Procesando…';
  try{ const r=await api("/ml/exchange",{method:"POST",body:JSON.stringify({code})});
    closeModal(); alert("✓ Conectado"+(r.username?" como "+r.username:"")); renderSettings();
  }catch(e){ err.textContent=e.message; }
}
async function mlDisconnect(){
  if(!confirm("¿Desconectar MercadoLibre? El equipo perderá el acceso a datos hasta reconectar."))return;
  try{ await api("/ml/disconnect",{method:"POST"}); renderSettings(); }catch(e){ alert(e.message); }
}
function mlAdvanced(hasSecret){
  openModal(`<h3>Configuración avanzada</h3>
    <div class="sub">APP ID y Client Secret de tu app en developers.mercadolibre.com.co. Redirect URI registrada: https://boun.com.co/oauth</div>
    <div id="advErr" class="err"></div>
    <input id="advId" class="field" placeholder="APP ID (Client ID)">
    <input id="advSecret" class="field" type="password" placeholder="${hasSecret?"Client Secret (guardado — escribe para cambiar)":"Client Secret"}">
    <input id="advRedir" class="field" placeholder="Redirect URI (opcional)" value="https://boun.com.co/oauth">
    <button class="btn-primary" onclick="saveAdv()">Guardar credenciales</button>`);
}
async function saveAdv(){
  const err=document.getElementById("advErr"); err.textContent="";
  try{ await api("/ml/credentials",{method:"POST",body:JSON.stringify({
    ml_app_id:val("advId"),ml_client_secret:val("advSecret"),ml_redirect_uri:val("advRedir")})});
    closeModal(); alert("Credenciales guardadas."); renderSettings();
  }catch(e){ err.textContent=e.message; }
}

function changePwDialog(){
  openModal(`<h3>Cambiar contraseña</h3><div class="sub">Define tu nueva contraseña.</div>
    <div id="pwErr" class="err"></div>
    <input id="pw1" class="field" type="password" placeholder="Nueva contraseña">
    <input id="pw2" class="field" type="password" placeholder="Repetir contraseña">
    <button class="btn-primary" onclick="doChangePw()">Guardar</button>`);
}
async function doChangePw(){
  const a=val("pw1"),b=val("pw2"),err=document.getElementById("pwErr"); err.textContent="";
  if(a.length<6){ err.textContent="Mínimo 6 caracteres."; return; }
  if(a!==b){ err.textContent="No coinciden."; return; }
  try{ await api("/change-password",{method:"POST",body:JSON.stringify({new_password:a})}); closeModal(); alert("Contraseña actualizada."); }
  catch(e){ err.textContent=e.message; }
}

// ── COLABORADORES// ── COLABORADORES ────────────────────────────────────────────────────────────
async function renderCollaborators(){
  const v=document.getElementById("view");
  v.innerHTML=`<div class="page-title">Colaboradores</div>
    <div class="page-sub">Crea y administra las cuentas de tu equipo.</div>
    <div class="inv-card" style="padding:16px;margin-bottom:16px">
      <div style="font-weight:700;color:var(--acc);margin-bottom:8px">Nuevo colaborador</div>
      <div id="colErr" class="err"></div>
      <div style="display:flex;gap:8px">
        <input id="colUser" class="field" style="margin:0" placeholder="Correo del colaborador">
        <input id="colPw" class="field" style="margin:0" placeholder="Contraseña temporal">
        <button class="btn-acc" onclick="createCol()">Crear</button>
      </div>
      <div class="muted" style="font-size:11px;margin-top:8px">El colaborador deberá cambiar la contraseña al iniciar sesión.</div>
    </div>
    <div id="colList"><div class="loading"><span class="spinner"></span> Cargando…</div></div>`;
  loadCols();
}
async function loadCols(){
  try{ const us=await api("/users");
    document.getElementById("colList").innerHTML=us.map(u=>{
      const adm=u.role==="admin";
      return `<div class="inv-card" style="padding:13px 16px;display:flex;align-items:center;gap:12px">
        <div style="flex:1"><b>${esc(u.username)}</b>${u.username===USER.username?' · tú':''}
          <div style="font-size:11px;color:${u.active?'var(--green)':'var(--red)'}">${adm?"Administrador":"Colaborador"}${u.active?"":" · desactivado"}</div></div>
        ${adm?"":`
          <button class="btn-ghost" onclick="resetCol('${esc(u.username)}')">Restablecer</button>
          <button class="btn-ghost" onclick="toggleCol('${esc(u.username)}',${!u.active})">${u.active?"Desactivar":"Activar"}</button>
          <button class="btn-danger" onclick="delCol('${esc(u.username)}')">Eliminar</button>`}
      </div>`;
    }).join("");
  }catch(e){ document.getElementById("colList").innerHTML=`<div class="red">${e.message}</div>`; }
}
async function createCol(){
  const u=val("colUser"),p=val("colPw"); const err=document.getElementById("colErr"); err.textContent="";
  if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(u)){ err.textContent="Correo inválido."; return; }
  if(p.length<6){ err.textContent="Contraseña mínimo 6 caracteres."; return; }
  try{ await api("/users",{method:"POST",body:JSON.stringify({username:u,password:p})});
    alert(`Colaborador creado.\nUsuario: ${u}\nContraseña: ${p}\n\nEnvíaselos para que entre.`);
    document.getElementById("colUser").value="";document.getElementById("colPw").value="";
    loadCols();
  }catch(e){ err.textContent=e.message; }
}
async function delCol(u){ if(!confirm(`¿Eliminar a "${u}"?`))return;
  try{ await api("/users/"+encodeURIComponent(u),{method:"DELETE"}); loadCols(); }catch(e){ alert(e.message); } }
async function toggleCol(u,a){ try{ await api("/users/"+encodeURIComponent(u)+"/active",{method:"PATCH",body:JSON.stringify({active:a})}); loadCols(); }catch(e){ alert(e.message); } }
async function resetCol(u){ const p=prompt(`Nueva contraseña temporal para ${u} (mín. 6):`); if(!p)return;
  if(p.length<6){ alert("Mínimo 6 caracteres."); return; }
  try{ await api("/users/"+encodeURIComponent(u)+"/reset",{method:"POST",body:JSON.stringify({new_password:p})});
    alert("Contraseña restablecida. El colaborador deberá cambiarla al entrar."); }catch(e){ alert(e.message); } }

// ── Utils ────────────────────────────────────────────────────────────────────
const esc=s=>(s==null?"":String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const val=id=>document.getElementById(id).value.trim();
const num=id=>parseFloat((document.getElementById(id).value||"").replace(/[^0-9.]/g,""))||0;
const bigImg=u=>u&&u.replace(/-I(\.[a-z]+)$/i,"-O$1");

// ── Init ─────────────────────────────────────────────────────────────────────
async function boot(){
  // ?k=<token> en la URL → guardar como llave de auto-login admin y limpiar URL
  const urlK = new URLSearchParams(location.search).get("k");
  if(urlK){ localStorage.setItem("boun_admin_k", urlK); history.replaceState({}, "", location.pathname); }
  const k = localStorage.getItem("boun_admin_k");
  if(k){
    try{
      const r = await fetch("/api/admin-login?k="+encodeURIComponent(k));
      if(r.ok){
        const j = await r.json();
        TOKEN=j.token; USER=j.user;
        localStorage.setItem("boun_token",TOKEN);
        localStorage.setItem("boun_user",JSON.stringify(USER));
        showApp(); return;
      } else { localStorage.removeItem("boun_admin_k"); }  // llave inválida
    }catch(e){}
  }
  if(TOKEN && USER){ showApp(); } else { document.getElementById("login").style.display="flex"; }
}
boot();

// ── CEREBRO — mapa de trabajo de la IA ───────────────────────────────────────
let CEREBRO_TIMER=null, CB_CLOCK_TIMER=null;
const CB_ICONS={
  box:'<path d="M21 8 12 3 3 8v8l9 5 9-5Z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
  chat:'<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4L3 21l1.1-3.6A8.4 8.4 0 1 1 21 11.5Z"/>',
  tag:'<path d="M3 7v5l9 9 5-5-9-9H3Z"/><circle cx="7" cy="11" r="1"/>',
  spark:'<path d="M12 3v6m0 6v6M3 12h6m6 0h6"/><path d="m6 6 3 3m6 6 3 3M18 6l-3 3M9 15l-3 3"/>',
  chart:'<path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="6"/><rect x="13" y="7" width="3" height="10"/>',
  target:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
  search:'<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  star:'<path d="m12 3 2.6 5.6 6.1.7-4.5 4.1 1.2 6L12 16.8 6.6 19.4l1.2-6L3.3 9.3l6.1-.7Z"/>',
  file:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 8v4l3 2"/>',
  bolt:'<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z"/>',
  alert:'<path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
};
const cbSvg=(n,sz=17,sw=1.7)=>`<svg width="${sz}" height="${sz}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round">${CB_ICONS[n]||""}</svg>`;
function cbCoParts(){
  const s=new Intl.DateTimeFormat("en-US",{timeZone:"America/Bogota",hour:"2-digit",minute:"2-digit",hour12:false,day:"numeric"}).formatToParts(new Date());
  const g=t=>+s.find(p=>p.type===t).value;
  return {h:g("hour")%24,m:g("minute"),day:g("day")};
}
function cbHHMM(min){const h=Math.floor(min/60),m=min%60,ap=h<12?"AM":"PM";let hh=h%12;if(hh===0)hh=12;return hh+(m?":"+String(m).padStart(2,"0"):"")+" "+ap;}
function cbTaskState(t){
  const {h,m,day}=cbCoParts(),nowMin=h*60+m;
  if(t.days && !t.days.includes(day)) return {s:"idle",label:"Programada",msg:t.idle,next:null};
  const sched=(t.hours||[]).map(x=>x*60).sort((a,b)=>a-b);
  let running=false,lastDone=null,next=null;
  for(const sm of sched){ if(nowMin>=sm && nowMin<sm+25) running=true; if(nowMin>=sm) lastDone=sm; if(nowMin<sm && next===null) next=sm; }
  if(running) return {s:"run",label:"Corriendo",msg:t.run||t.idle,next};
  if(lastDone!==null) return {s:"ok",label:"Hecha hoy",msg:t.done||t.idle,next};
  return {s:"idle",label:"En espera",msg:t.idle,next};
}
function cbClock(){
  const el=document.getElementById("cbClk"); if(!el) return;
  const now=new Date();
  el.textContent=new Intl.DateTimeFormat("es-CO",{timeZone:"America/Bogota",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(now);
  const d=document.getElementById("cbClkD"); if(d) d.textContent=new Intl.DateTimeFormat("es-CO",{timeZone:"America/Bogota",weekday:"long",day:"numeric",month:"long"}).format(now);
}
function cbPromptFor(t){
  const id=t.id||'';
  const base=`Ejecuta ahora la tarea automatizada de BOUN «${t.nombre}» (id: ${id}).`;
  const path=t.auto?'':` Está en /Users/admin/Claude/Scheduled/${id}/SKILL.md — léela y córrela siguiendo sus pasos.`;
  return `${base}${path} Al terminar dame un resumen y reporta el estado al Cerebro.`;
}
function cbSkillPromptFor(s){
  return `Usa la skill «${s.nombre}» (${s.tag}) para ayudarme con la tienda BOUN ahora.`;
}
function cbAlertPromptFor(a){
  return `Resuelve este pendiente del Cerebro BOUN: «${a.title}». Contexto: ${a.txt} Investiga la causa, propón y/o aplica la solución, y al terminar dime cómo quedó.`;
}
function cbFallbackCopy(txt){const ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(ta);}
function cbCopy(el){
  const txt=decodeURIComponent(el.dataset.p||'');
  const done=()=>{el.textContent='✓ ¡Copiado! Pégalo en Claude';el.classList.add('ok');setTimeout(()=>{el.textContent='⧉ Abrir en Claude';el.classList.remove('ok');},2500);};
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(done).catch(()=>{cbFallbackCopy(txt);done();});}
  else{cbFallbackCopy(txt);done();}
}
async function renderCerebro(){
  if(CEREBRO_TIMER){clearInterval(CEREBRO_TIMER);CEREBRO_TIMER=null;}
  if(CB_CLOCK_TIMER){clearInterval(CB_CLOCK_TIMER);CB_CLOCK_TIMER=null;}
  const v=document.getElementById("view");
  v.innerHTML=`<div class="cb">
    <div class="cb-top">
      <div>
        <div class="page-title">🧠 Cerebro BOUN</div>
        <div class="page-sub">Mapa de trabajo de la IA en la empresa — automatización en tiempo real</div>
      </div>
      <div class="cb-clockbox">
        <div class="cb-clk" id="cbClk">--:--:--</div>
        <div class="cb-clkd" id="cbClkD">—</div>
        <div class="cb-live"><span class="cb-dot"></span> Sistema activo · Colombia (UTC-5)</div>
      </div>
    </div>
    <div id="cbBody"><div class="loading"><span class="spinner"></span> Cargando el cerebro…</div></div>
  </div>`;
  cbClock();
  CB_CLOCK_TIMER=setInterval(cbClock,1000);   // el reloj corre desde ya (no se congela durante el cold-start)
  let data=null;
  try{ data=await api("/cerebro"); }
  catch(e){ data={ok:false}; }
  drawCerebro(data);
  CEREBRO_TIMER=setInterval(()=>{ cbClock(); if(document.getElementById("cbBody")) drawCerebro(data); },20000);
}
function drawCerebro(data){
  const body=document.getElementById("cbBody"); if(!body) return;
  const m=(data&&data.motor)||{};
  const tasks=(data&&data.tasks)||CB_FALLBACK_TASKS;
  const skills=(data&&data.skills)||CB_FALLBACK_SKILLS;
  const alertas=(data&&data.alertas)||[];

  // — estado del motor —
  const onN='<span class="cb-ndot on"></span>';
  const warnN='<span class="cb-ndot warn"></span>';
  const chTxt=(m.apply_channels&&m.apply_channels.length)?m.apply_channels.length+" canales escribiendo":"DRY-RUN (no escribe)";
  const nodes=[
    {dot:m.dry_run?warnN:onN,nm:"Sync de stock",d:`Escritura real · ${chTxt} · tope ${m.max_delta||"∞"} u.`,st:m.sync_enabled?"Escuchando ventas":"Ingesta pausada",warn:m.dry_run||!m.sync_enabled},
    {dot:m.scan_daily?onN:warnN,nm:"Escaneo diario",d:`Reconcilia Web → canales cada día a las ${m.scan_daily_hour!=null?m.scan_daily_hour+":00":"4:00"}.`,st:m.scan_daily?"Activo":"Desactivado",warn:!m.scan_daily},
    {dot:m.scan_reactivate?onN:warnN,nm:"Reactivación",d:"Revive publicaciones de ML agotadas en cuanto hay stock.",st:m.scan_reactivate?"Vigilando agotados":"Desactivada",warn:!m.scan_reactivate},
    {dot:'<span class="cb-ndot ml"></span>',nm:"Poller ML",d:"Lee ventas de MercadoLibre cada ~3 min (idempotente).",st:"Sondeando"},
    {dot:'<span class="cb-ndot fala"></span>',nm:"Poller Falabella",d:"Lee ventas de Seller Center cada ~3 min, con reintentos.",st:"Sondeando"},
    {dot:'<span class="cb-ndot shop"></span>',nm:"Webhooks Shopify",d:"Ventas de BOUN + KAT entran al instante por webhook (HMAC).",st:"Conectado"},
    {dot:'<span class="cb-ndot combo"></span>',nm:"Combos / kits",d:"Stock auto-calculado; al venderse descuenta sus componentes.",st:"Activo"},
    {dot:warnN,nm:"Regla temporal",d:'"ML solo bodega Bogotá" mientras Yopal no esté en ML.',st:m.ml_solo_bogota?"Vigente":"Inactiva",warn:m.ml_solo_bogota},
  ];
  const coreHtml=`<div class="cb-core">
    <div class="cb-core-head"><div class="cb-orb"></div>
      <div><div class="cb-core-t">Motor de sincronización · 4 canales</div>
      <div class="cb-core-s">Cada venta descuenta el inventario central y reparte el stock a MercadoLibre, Falabella y Shopify (BOUN + KAT)</div></div></div>
    <div class="cb-nodes">${nodes.map(n=>`<div class="cb-node"><div class="cb-nh">${n.dot}${n.nm}</div><div class="cb-nd">${n.d}</div><div class="cb-nst ${n.warn?"warn":""}"><span class="cb-pulse ${n.warn?"warn":""}"></span>${n.st}</div></div>`).join("")}</div>
  </div>`;

  // — KPIs —
  let runN=0,doneN=0;
  tasks.forEach(t=>{const s=cbTaskState(t);if(s.s==="run")runN++;if(s.s==="ok")doneN++;});
  const kpis=`<div class="cb-kpis">
    <div class="cb-kpi run"><div class="cb-kc">${cbSvg("bolt",13,2)} Procesos activos</div><div class="cb-kv">${tasks.length+8}</div><div class="cb-km">núcleo autónomo + ${tasks.length} tareas</div></div>
    <div class="cb-kpi"><div class="cb-kc">${cbSvg("clock",13,2)} Corriendo ahora</div><div class="cb-kv">${runN}</div><div class="cb-km">${runN?"ejecutándose ahora":"en espera de la próxima ventana"}</div></div>
    <div class="cb-kpi"><div class="cb-kc">${cbSvg("clock",13,2)} Completadas hoy</div><div class="cb-kv">${doneN}</div><div class="cb-km">sin errores · últimas 24 h</div></div>
    <div class="cb-kpi err"><div class="cb-kc">${cbSvg("alert",13,2)} Pendientes / fallas</div><div class="cb-kv">${alertas.length}</div><div class="cb-km">requieren tu decisión</div></div>
  </div>`;

  // — jornada / timeline —
  const {h,m:mm}=cbCoParts(),nowMin=h*60+mm,dayMin=1440;
  const marks=[{hh:4,l:"Escaneo motor"},{hh:8,l:"Inventario ML"},{hh:9,l:"Preguntas ML"},{hh:16,l:"Preguntas ML"},{hh:17,l:"Pauta Falab."},{hh:23,l:"Contenido Falab."}];
  let nextFound=false;
  const ticks=marks.map((mk,i)=>{const mn=mk.hh*60,pct=mn/dayMin*100;let cls=(i%2?"lo":"");if(mn<=nowMin)cls+=" done";else if(!nextFound){cls+=" next";nextFound=true;}return `<div class="cb-tick ${cls}" style="left:${pct}%"><div class="cb-tkh">${cbHHMM(mn)}</div><div class="cb-tkd"></div><div class="cb-tkl">${mk.l}</div></div>`;}).join("");
  const tl=`<div class="cb-sec">${cbSvg("clock",16)}<h3>Jornada de hoy</h3><span class="cb-tag">cuándo actúa la IA a lo largo del día</span></div>
    <div class="cb-tl"><div class="cb-track"><div class="cb-line"></div><div class="cb-prog" style="width:${nowMin/dayMin*100}%"></div>${ticks}<div class="cb-now" style="left:${nowMin/dayMin*100}%"></div></div>
    <div class="cb-legend"><span><i class="lg done"></i> ejecutada</span><span><i class="lg next"></i> próxima</span><span><i class="lg"></i> programada</span></div></div>`;

  // — tarjetas de tareas —
  const cardHtml=(t)=>{
    const st=cbTaskState(t), hb=t.heartbeat||{};
    const label= hb.status? ({ok:"Hecha",run:"Corriendo",warn:"Atención",err:"Falló"}[hb.status]||st.label) : st.label;
    const sc= hb.status? ({ok:"ok",run:"run",warn:"warn",err:"err"}[hb.status]||st.s) : st.s;
    const msg= hb.msg || st.msg;
    const accent=t.canal==="mercadolibre"?"ml":t.canal==="falabella"?"fala":"otro";
    const nm=t.canal==="mercadolibre"?"MercadoLibre":t.canal==="falabella"?"Falabella":(t.canal?t.canal.charAt(0).toUpperCase()+t.canal.slice(1):"Proceso");
    const nowic= sc==="run"?'<span class="cb-rdot"></span>': sc==="ok"?`<span style="color:var(--cb-ok)">${cbSvg("clock",16,2.2)}</span>`: sc==="err"||sc==="warn"?`<span style="color:var(--cb-${sc==="err"?"err":"warn"})">${cbSvg("alert",16,2)}</span>`:`<span class="muted">${cbSvg("clock",16,2)}</span>`;
    const next=st.next!=null?("Próxima "+cbHHMM(st.next)):"—";
    const pr=encodeURIComponent(cbPromptFor(t));
    return `<div class="cb-card">
      <span class="cb-chan ${accent}">${nm}</span>
      <div class="cb-ch"><div class="cb-cic ${accent}">${cbSvg(t.icon||"box",18)}</div>
        <div><div class="cb-ct">${t.nombre}</div><div class="cb-ccad">${cbSvg("clock",11,2)} ${t.cad}</div></div></div>
      <div class="cb-desc">${t.desc}</div>
      <div class="cb-now-box"><span class="cb-nowic">${nowic}</span><span class="cb-nowt"><b>${sc==="run"?"Ahora mismo":label}</b><span>${msg}</span></span></div>
      <div class="cb-foot"><span class="cb-st ${sc}"><span class="cb-sdot"></span>${label}</span><span>${next}</span></div>
      <button class="cb-open" data-p="${pr}" onclick="cbCopy(this)">⧉ Abrir en Claude</button>
    </div>`;
  };
  const ml=tasks.filter(t=>t.canal==="mercadolibre"),fa=tasks.filter(t=>t.canal==="falabella");
  const otros=tasks.filter(t=>t.canal!=="mercadolibre"&&t.canal!=="falabella");
  const tasksHtml=`
    <div class="cb-sec ml">${cbSvg("box",16)}<h3>Tareas programadas · MercadoLibre</h3><span class="cb-tag">cuenta BOUN COL</span></div>
    <div class="cb-grid">${ml.map(cardHtml).join("")}</div>
    <div class="cb-sec fa">${cbSvg("chart",16)}<h3>Tareas programadas · Falabella</h3><span class="cb-tag">Seller Center + Retail Media</span></div>
    <div class="cb-grid">${fa.map(cardHtml).join("")}</div>`
    + (otros.length?`<div class="cb-sec"><span style="color:var(--cb)">${cbSvg("bolt",16)}</span><h3>Otros procesos · nuevos</h3><span class="cb-tag">se suman solos al reportar al Cerebro</span></div>
    <div class="cb-grid">${otros.map(cardHtml).join("")}</div>`:"");

  // — skills —
  const skillsHtml=`<div class="cb-sec">${cbSvg("star",16)}<h3>Skills disponibles</h3><span class="cb-tag">capacidades que la IA puede invocar</span></div>
    <div class="cb-grid sk">${skills.map(s=>`<div class="cb-skill"><div class="cb-sk-top"><div class="cb-sic">${cbSvg(s.icon||"file",17)}</div><div><div class="cb-skt">${s.nombre}</div><div class="cb-skd">${s.desc}</div></div><span class="cb-pill">${s.tag}</span></div><button class="cb-open" data-p="${encodeURIComponent(cbSkillPromptFor(s))}" onclick="cbCopy(this)">⧉ Abrir en Claude</button></div>`).join("")}</div>`;

  // — pendientes —
  const alertsHtml=`<div class="cb-sec err">${cbSvg("alert",16)}<h3>Pendientes de la IA · requieren solución</h3><span class="cb-tag">detectar y resolver</span></div>
    <div class="cb-grid al">${alertas.map(a=>{const w=a.sev==="warn";return `<div class="cb-alert ${w?"w":""}"><div class="cb-ah"><div class="cb-aic">${cbSvg("alert",16,2)}</div><h4>${a.title}</h4><span class="cb-sev">${w?"Atención":"Bloqueado"}</span></div><p>${a.txt}</p><button class="cb-open" data-p="${encodeURIComponent(cbAlertPromptFor(a))}" onclick="cbCopy(this)">⧉ Abrir en Claude</button></div>`;}).join("")||'<div class="muted" style="padding:10px">Sin pendientes. Todo en orden. ✅</div>'}</div>`;

  const offline = (data&&data.ok===false)?'<div class="cb-offline">⚠ No se pudo leer el estado del motor (la web puede estar despertando). Mostrando estado por horario.</div>':'';

  body.innerHTML = offline + kpis +
    `<div class="cb-sec">${cbSvg("bolt",16)}<h3>Núcleo autónomo</h3><span class="cb-tag">Web BOUN · siempre encendido · fuente de verdad del inventario</span></div>` +
    coreHtml + tl + tasksHtml + skillsHtml + alertsHtml;
}
// Respaldo si el backend aún no expone /api/cerebro (cold-start o deploy viejo).
const CB_FALLBACK_TASKS=[
  {id:"ml1",canal:"mercadolibre",nombre:"Inventario diario",icon:"box",cad:"Diario · 8:00 AM",hours:[8],days:null,desc:"Revisa publicación por publicación; en las agotadas quita el Full y deja el stock en 0.",run:"Recorriendo publicaciones…",done:"Revisión completa · agotadas marcadas",idle:"Listo hasta mañana 8:00 AM"},
  {id:"ml2",canal:"mercadolibre",nombre:"Preguntas, reclamos y facturación",icon:"chat",cad:"2× día · 9:00 AM y 4:00 PM",hours:[9,16],days:null,desc:"Responde compradores, gestiona reclamos y envía el RUT a Edgar por WhatsApp.",run:"Leyendo preguntas y reclamos…",done:"Bandeja respondida · facturación al día",idle:"Próxima pasada a las 4:00 PM"},
  {id:"ml3",canal:"mercadolibre",nombre:"Campaña promo mensual (BOUN)",icon:"tag",cad:"Mensual · día 7, 1:00 PM",hours:[13],days:[7],desc:"Crea la BOUN del mes y alinea promociones a precios del mes anterior.",run:"Armando la BOUN del mes…",done:"BOUN lista para tu revisión",idle:"Programada para el día 7"},
  {id:"dn1",canal:"mercadolibre",nombre:"Protección de marca (denuncias)",icon:"alert",cad:"Diario · 8:00 PM",hours:[20],days:null,desc:"Busca tu marca en el Brand Protection Program, denuncia a quienes se cuelgan de tus catálogos BOUN y hace seguimiento del estado.",run:"Detectando y denunciando infractores…",done:"Infractores denunciados · estados actualizados",idle:"Próxima corrida a las 8:00 PM"},
  {id:"fa1",canal:"falabella",nombre:"Corrida diaria de contenido",icon:"spark",cad:"Diario · 11:00 PM",hours:[23],days:null,desc:"Sube el puntaje de contenido a 100, pide reseñas y aplica el playbook 1★.",run:"Optimizando fichas y reseñas…",done:"Catálogo en puntaje 100 · reporte listo",idle:"Próxima corrida a las 11:00 PM"},
  {id:"fa2",canal:"falabella",nombre:"Auditoría quincenal",icon:"chart",cad:"Días 1 y 15 · 9:00 AM",hours:[9],days:[1,15],desc:"Audita ventas, productos killers y ROAS contra la línea base.",run:"Auditando ventas y ROAS…",done:"Auditoría lista vs. línea base",idle:"Próxima auditoría el día 1"},
  {id:"fa3",canal:"falabella",nombre:"Ajuste de pauta quincenal",icon:"target",cad:"Días 1 y 16 · 5:00 PM",hours:[17],days:[1,16],desc:"Optimiza campañas: pausa sin stock, recorta ACOS alto y escala el ROAS sano.",run:"Recalculando campañas…",done:"Pauta optimizada · sin stock pausado",idle:"Próximo ajuste el día 1"},
];
const CB_FALLBACK_SKILLS=[
  {nombre:"Optimizador SEO Falabella",icon:"search",tag:"Chrome",desc:"Optimiza títulos, descripciones y puntaje de contenido con tendencias reales de Colombia."},
  {nombre:"Playbook reseñas 1★",icon:"star",tag:"Embebida",desc:"Flujo duplicar → corregir → eliminar para neutralizar reseñas de una estrella."},
  {nombre:"Reportes (Word · Excel · PDF)",icon:"file",tag:"Documentos",desc:"Genera auditorías, resúmenes de ventas y reportes operativos profesionales."},
];
