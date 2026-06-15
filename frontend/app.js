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
  if(r.status===401){ logoutLocal(); throw new Error("Sesión expirada"); }
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.detail || "Error");
  return j;
}

// ── Auth ──────────────────────────────────────────────────────────────────
async function doLogin(){
  const u=document.getElementById("lu").value, p=document.getElementById("lp").value;
  const err=document.getElementById("loginErr"); err.textContent="";
  try{
    const r=await api("/login",{method:"POST",body:JSON.stringify({username:u,password:p})});
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
  ["ventas","↗  Ventas"],
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
}
async function refreshColaBadge(){
  try{
    const r=await api("/cola-bodega/count");
    const b=document.getElementById("badge-cola");
    if(b) b.textContent=r.count>0?r.count:"", b.style.display=r.count>0?"inline-block":"none";
  }catch(e){}
}
function go(id){
  document.querySelectorAll(".nav a").forEach(a=>a.classList.toggle("active",a.dataset.nav===id));
  if(id==="dashboard") renderDashboard();
  else if(id==="ventas") renderSales();
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
    </div><div style="display:flex;gap:8px">
      <button class="btn-ghost" onclick="exportInv()">⬇ Exportar inventario</button>
      <button class="btn-acc" onclick="newProduct()">＋ Nuevo producto</button></div></div>
    <div id="invKpis" class="kpis"></div>
    <div id="invList"><div class="loading"><span class="spinner"></span> Cargando inventario…</div></div>`;
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

function invCard(p){
  const u=prodUnits(p), unit=prodCostUnit(p);
  const sug=Math.max(0,Math.ceil((+p.sold60_total||0)/60*90 - u));
  const photo=p.thumb?`<img class="inv-photo" src="${bigImg(p.thumb)}">`:`<div class="inv-photo"></div>`;
  return `<div class="inv-card" data-pid="${p.id}">
    <div class="inv-head">
      <span class="expand" onclick="togglePanel(${p.id})">▸</span>
      ${photo}
      <span class="code-chip">📦 ${esc(p.code)}</span>
      <div style="flex:1">
        <div class="inv-name">${esc(p.name)}</div>
        <div class="inv-meta">${p.n_links} publicación${p.n_links!==1?"es":""} asignada${p.n_links!==1?"s":""} ${chCounts(p.n_by_channel)}${p.created_by?" · creado por "+esc(p.created_by):""}</div>
      </div>
      <button class="btn-ghost" onclick="assignDialog(${p.id})">Asignar publicaciones</button>
      <button class="btn-ghost" onclick="editProduct(${p.id})">✏</button>
      ${isAdmin()?`<button class="btn-danger" onclick="delProduct(${p.id})">✕</button>`:""}
    </div>
    <div class="inv-strip">
      ${fcol("Costo prod.",inp(p.id,"cost_product",p.cost_product))}
      ${fcol("Envío",inp(p.id,"cost_shipping",p.cost_shipping))}
      ${fcolRO("Costo total",cop(unit),unit?"acc":"red")}
      <div class="vsep"></div>
      ${fcol("Bod. Bogotá",inp(p.id,"qty_bogota",p.qty_bogota,64))}
      ${fcol("Bod. Yopal",inp(p.id,"qty_yopal",p.qty_yopal,64))}
      ${fcolRO("ML Full",p.qty_full||0)}
      ${fcol("En camino",inp(p.id,"qty_transit",p.qty_transit,64))}
      ${fcolRO("Inv. total",u,u?"acc":"red")}
      <div class="vsep"></div>
      ${fcolRO("Costo inv.",cop(unit*u),"amber")}
      ${fcolRO("Gan. esperada",cop((+p.avg_net||0)*u),"green")}
      ${fcolRO("Valor venta",cop((+p.avg_price||0)*u))}
      ${fcolRO("Margen prom.",(+p.avg_margin)?(+p.avg_margin).toFixed(1)+"%":"—",mgColor(+p.avg_margin))}
      ${fcolRO("ROAS prom.",(+p.avg_roas)?(+p.avg_roas).toFixed(2)+"x":"—",roasColor(+p.avg_roas))}
      ${fcolRO("ACOS prom.",(+p.avg_acos)?(+p.avg_acos).toFixed(1)+"%":"—",acosColor(+p.avg_acos))}
      <div class="vsep"></div>
      ${fcolRO("Vend. 60d",p.sold60_total||0)}
      ${fcolRO("Sug. compra",sug?("+"+sug+" u"):"✓ cubierto",sug?"red":"green")}
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
        <button id="scanPrevBtn" class="btn-acc" onclick="scanStart('preview')">🔍 Previsualizar escaneo</button>
        <button id="scanApplyBtn" class="btn-ghost" onclick="scanStart('apply')">✍ Aplicar correcciones</button>
      </div>
      <div id="scanOut" style="margin-top:14px"></div>
      <div style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px">
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
  }catch(e){}
  const out=document.getElementById("scanOut");
  if(!out) return;
  let s; try{ s=await api("/sync/scan-status"); }catch(e){ return; }
  if(s.status==="running") scanPoll();
  else if(s.status==="done" && s.counts && s.rows_total) out.innerHTML=scanResultHTML(s);
}
async function scanDailySave(){
  const en=document.getElementById("scanDaily").checked;
  let h=parseInt(document.getElementById("scanDailyHour").value,10); if(isNaN(h))h=4;
  const msg=document.getElementById("scanDailyMsg");
  try{
    await api("/sync/apply-config",{method:"POST",body:JSON.stringify({scan_daily:en,scan_daily_hour:h})});
    if(msg){ msg.textContent=en?`✓ activado · ${h}:00`:"✓ desactivado"; msg.className="green"; setTimeout(()=>{if(msg)msg.textContent="";},2500); }
  }catch(e){ if(msg){ msg.textContent=e.message; msg.className="red"; } }
}
async function scanStart(mode){
  const chans=[...document.querySelectorAll(".scanch:checked")].map(e=>e.value);
  if(!chans.length){ alert("Elige al menos un canal."); return; }
  if(mode==="apply" && !confirm("Vas a ESCRIBIR stock real en: "+chans.map(scanChLabel).join(", ")+".\n\nCada publicación (excepto Full y catálogo) quedará igualada al disponible de tu inventario, SIN tope de salto. Esto corrige agotadas y desfases en todos los canales elegidos.\n\n¿Confirmas?")) return;
  const out=document.getElementById("scanOut");
  scanSetBusy(true);
  if(out) out.innerHTML='<div class="loading"><span class="spinner"></span> Iniciando escaneo…</div>';
  try{
    await api("/sync/scan-start",{method:"POST",body:JSON.stringify({mode,channels:chans})});
    scanPoll();
  }catch(e){
    // 409 = ya hay un escaneo en curso → engancha su progreso en vez de solo el error.
    if(/curso/i.test(e.message||"")){ scanPoll(); }
    else { scanSetBusy(false); if(out) out.innerHTML=`<div class="red" style="font-size:12px">${esc(e.message)}</div>`; }
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
  return `<div>
      <div style="font-size:12px;color:var(--muted);margin-bottom:6px"><span class="spinner"></span> ${verbo}… <b>${done||0}/${total||0}</b> productos · ${pct}%</div>
      <div style="height:9px;background:var(--surf);border:1px solid var(--border);border-radius:6px;overflow:hidden">
        <div style="height:100%;width:${pct}%;background:var(--acc);border-radius:6px;transition:width .35s ease"></div>
      </div></div>`;
}
async function scanPoll(){
  let s; try{ s=await api("/sync/scan-status"); }
  catch(e){ scanSetBusy(false); const o=document.getElementById("scanOut"); if(o) o.innerHTML=`<div class="red" style="font-size:12px">${esc(e.message)}</div>`; return; }
  // Releemos el contenedor en CADA tick: si Configuración se re-renderizó, el
  // <div id="scanOut"> es otro nodo. No cortamos la cadena si está null (el
  // escaneo sigue en el servidor); seguimos sondeando y pintamos cuando reaparezca.
  if(s.status==="running"){
    scanSetBusy(true);
    const out=document.getElementById("scanOut");
    if(out) out.innerHTML=scanBar(s.done,s.total,s.mode);
    setTimeout(scanPoll,2000); return;
  }
  scanSetBusy(false);
  const out=document.getElementById("scanOut");
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
      <span style="font-size:12px">${dry?"Cambiarían":"Escritas"}: <b class="green">${c.cambios||0}</b> · Ya alineadas: ${c.sin_cambio||0} · Saltadas (Full/catálogo): ${c.saltados||0} · Errores: <span class="${(c.errores||0)?"red":""}">${c.errores||0}</span></span></div>`;
  if(!rows.length) return head+`<div class="muted" style="font-size:12px">Todo está alineado con tu inventario. No hay cambios que mostrar.</div>`;
  const trs=rows.slice(0,500).map(r=>{
    const col=r.accion.startsWith("saltado")?"var(--dim)":r.accion==="error"?"var(--red)":"var(--green)";
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
      ${dry&&(c.cambios||0)?`<button class="btn-acc" style="margin-top:12px" onclick="scanStart('apply')">✍ Aplicar estas ${c.cambios} correcciones</button>`:""}`;
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
