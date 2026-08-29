const MAX_POINTS = 10;
const POINT_NAME_MAX_LENGTH = 25;
const POINT_PALETTE = ['#d94841','#6f56a8','#2f8b57','#d17b27','#2878b8','#a74e87','#557a2a','#b49724','#4e6cb3','#8a5b3d'];
const POINT_COLORS = Object.fromEntries(Array.from({length:MAX_POINTS},(_,i)=>[`O${i+1}`,POINT_PALETTE[i]]));
const DEFAULT_BASIN_COLOR = '#9b7300';
const DEFAULT_RIVER_COLOR = '#0083d7';
const DEFAULT_BASEMAP = 'world-topo';
const APP_STATE_KEY = 'delineasiDtaUiStateV85';
const MULTI_MODE_HINT_KEY = 'delineasiDtaMultiModeHintV1';
const USAGE_NOTICE_KEY = 'delineasiDtaUsageNoticeV1';
const RIVER_ZOOM = {1:6.5,2:6.5,3:10.5,other:12.5};
const RIVER_FULL_DETAIL_ZOOM = 14;
const RIVER_KEYS = ['1','2','3','other'];
const KARST_MESSAGE = 'Delineasi berbasis topografi permukaan tidak valid untuk kawasan karst. Sistem hidrologi karst didominasi oleh sungai bawah tanah sehingga batas topografi permukaan tidak mencerminkan daerah tangkapan air yang sebenarnya.';
const DTA_CONFIG = window.DTA_CONFIG || {};
const MAP_ASSETS_BASE = String(DTA_CONFIG.mapAssetsBase || '').replace(/\/$/,'');
const MAP_ASSETS_VERSION = String(DTA_CONFIG.mapAssetsVersion || '');
const MAP_ASSET_FILES = {
  'official-basins':'official_basins.geojson',
  'official-rivers-z6-8':'official_rivers_z6_8.geojson',
  'official-rivers-z8-10':'official_rivers_z8_10.geojson',
  'official-rivers-z10-11':'official_rivers_z10_11.geojson',
  'official-rivers-z11-12':'official_rivers_z11_12.geojson',
  'official-rivers-z12-14':'official_rivers_z12_14.geojson',
  'official-rivers':'official_rivers.geojson'
};

function browserClientId(){
  const key='delineasiDtaClientIdV1';
  try{
    let value=sessionStorage.getItem(key);
    if(!value){value=globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`;sessionStorage.setItem(key,value);}
    return value;
  }catch(_){return `${Date.now()}-${Math.random().toString(36).slice(2)}`;}
}
const DTA_CLIENT_ID = browserClientId();

function hasUsageNoticeBeenShownThisBrowserSession(){
  try{
    return document.cookie.split(';').some(cookie=>cookie.trim().startsWith(`${USAGE_NOTICE_KEY}=`));
  }catch(_){return false;}
}
function markUsageNoticeShownThisBrowserSession(){
  try{
    const secure=location.protocol==='https:'?'; Secure':'';
    document.cookie=`${USAGE_NOTICE_KEY}=shown; Path=/; SameSite=Lax${secure}`;
  }catch(_){}
}
function showUsageNoticeOncePerBrowserSession(){
  if(hasUsageNoticeBeenShownThisBrowserSession())return;
  // A session cookie survives refreshes and tab closures, but expires when the
  // browser session ends. Mark it as soon as the notice is shown so reopening a
  // tab in the same browser session does not show the notice a second time.
  markUsageNoticeShownThisBrowserSession();
  openMapModal($('usageNoticeModal'));
}

function clearLegacyPersistentState(){
  try{
    localStorage.removeItem(APP_STATE_KEY);
    localStorage.removeItem('delineasiDtaUiStateV82');
    localStorage.removeItem('delineasiDtaUiStateV72');
    localStorage.removeItem(MULTI_MODE_HINT_KEY);
    localStorage.removeItem(USAGE_NOTICE_KEY);
  }catch(_){}
}
clearLegacyPersistentState();
function readAppState(){try{return JSON.parse(sessionStorage.getItem(APP_STATE_KEY)||'{}')||{};}catch(_){return {};}}
const restoredState = readAppState();
if(restoredState.pointColors&&typeof restoredState.pointColors==='object'){for(let i=1;i<=MAX_POINTS;i++){const id=`O${i}`;if(restoredState.pointColors[id])POINT_COLORS[id]=restoredState.pointColors[id];}}
let info = {};
const uiLanguage = 'id';
let decimalSeparator = restoredState.decimalSeparator === '.' ? '.' : ',';
let points = Array.isArray(restoredState.points)?restoredState.points.slice(0,MAX_POINTS).map(p=>({...p,label:clampPointName(p?.label)})):[];
let batchResult = null;
let studyBounds = null;
let pointPopup = null;

// Only one unconfirmed "Tambahkan Titik" request/popup may exist at a time.
// Rapid map clicks use latest-click-wins semantics.
let pointPopupRequestSerial = 0;
let pointPopupAbortController = null;
let mapPointClickTimer = null;
const MAP_POINT_CLICK_DEBOUNCE_MS = 180;

let pointInputMode = restoredState.pointInputMode === 'multi' || restoredState.multiPointMode === true ? 'multi' : 'single';
// Adding points is an explicit interaction session and always starts idle after a reload.
let addingPoints = false;
let locationPreview = null;
let locationPreviewPopup = null;
let measureMode = false;
let measureCoords = [];
let measurePreview = null;
let sidebarCollapsed = Boolean(restoredState.sidebarCollapsed);
let selectedLightBasemap = restoredState.selectedLightBasemap || DEFAULT_BASEMAP;
let currentBasemap = restoredState.currentBasemap || (document.documentElement.getAttribute('data-theme')==='dark' ? 'esri-dark-gray' : selectedLightBasemap);
let headerHideTimer = null;
let activePointId = restoredState.activePointId || (points.length ? points[points.length-1].point_id : null);
let processingPointIds = new Set();
let undoDeleteState = null;
let undoDeleteTimer = null;
let persistTimer = null;
let dtaHoverPopup = null;
let hoverPointId = null;
let hoverDelayTimer = null;
let hoverCandidateId = null;
let hoverCandidateLngLat = null;
let hoverCandidateKind = null;
let hoverShownKind = null;
let hoverEmphasisId = null;
let hoverEmphasisKind = null;
let pointListSortable = null;
let suppressCardToggleUntil = 0;
let previewSnapState = null;
let movePointId = null;
let mapPointerFrame = null;
let lastMapPointerEvent = null;
let progressiveMoving = false;
let appToastTimer = null;
// Prevent an older slow delineation response from overwriting a newer outlet or setting.
let delineationRequestSerial = 0;
// A request id identifies a fetch, while an operation id identifies the latest
// user intent. Reconciliation may create another fetch inside the same operation.
let delineationOperationSerial = 0;
const latestDelineationSerialByPoint = new Map();
let delineationAbortController = null;

// Sidebar and map popup are two views of the same DTA state.
const pointNameDrafts = new Map();
const pointNameSaving = new Set();
const restoredNameDrafts = (restoredState.nameDrafts && typeof restoredState.nameDrafts === 'object') ? restoredState.nameDrafts : {};
for(const p of points){
  const saved=(p.label?.trim()||p.point_id);
  pointNameDrafts.set(p.point_id, Object.prototype.hasOwnProperty.call(restoredNameDrafts,p.point_id) ? clampPointName(restoredNameDrafts[p.point_id]) : clampPointName(saved));
}

const DTA_ACTIONS = [
  {id:'zoomOutlet', label:'Outlet', icon:'map-pin', sidebarClass:'zoom-outlet'},
  {id:'zoomDta', label:'DTA', icon:'scan', sidebarClass:'zoom-point'},
  {id:'copyCoordinate', label:'Salin', icon:'copy', sidebarClass:'copy-point-coordinate'},
  {id:'moveOutlet', label:'Pindah', icon:'move', sidebarClass:'move-point'},
  {id:'changeColor', label:'Warna', icon:'palette', sidebarClass:'change-point-color'},
  {id:'delete', label:'Hapus', icon:'trash-2', sidebarClass:'remove-point', destructive:true},
];
let basinLabelData = null;
let riverLabelData = null;
let riverLabelDataKey = null;
let currentRiverAssetKey = null;
let hiddenRiverLabelIds = [];
let lastRiverLabelFilterSignature = '';
const modalCameraContext = new WeakMap();

const $ = id => document.getElementById(id);
const statusEl = $('status');
const pointListEl = $('pointList');
const pointCountEl = $('pointCount');
const relationshipPanel = $('relationshipPanel');
const relationshipContent = $('relationshipContent');
const snapRadiusEl = $('snapRadius');
const boundaryMatchEl = $('boundaryMatch');
const layerPanel = $('layerPanel');
const searchResultsEl = $('searchResults');

function restorePreferenceControls(){
  const c=restoredState.controls||{};
  const values={snapRadius:c.snapRadius,boundaryMatch:c.boundaryMatch,hillshadeOpacity:c.hillshadeOpacity,hatchOpacity:c.hatchOpacity,lineWidth:c.lineWidth,basinColor:c.basinColor,riverColor:c.riverColor};
  for(const [id,value] of Object.entries(values)){if(value!==undefined&&$(id))$(id).value=String(value);}
  const checks={showHillshade:c.showHillshade,showBasins:c.showBasins,showBasinLabels:c.showBasinLabels,showRivers:c.showRivers,autoRiverZoom:c.autoRiverZoom,showRiverLabels:c.showRiverLabels,showHatch:c.showHatch};
  for(const [id,value] of Object.entries(checks)){if(value!==undefined&&$(id))$(id).checked=Boolean(value);}
  if(c.riverOrders){document.querySelectorAll('.river-order-toggle').forEach(x=>{if(c.riverOrders[x.dataset.order]!==undefined)x.checked=Boolean(c.riverOrders[x.dataset.order]);});}
  if($('hillshadeOpacityValue'))$('hillshadeOpacityValue').textContent=`${$('hillshadeOpacity').value}%`;
  if($('hatchOpacityValue'))$('hatchOpacityValue').textContent=`${$('hatchOpacity').value}%`;
}
function getCameraState(){try{const c=map.getCenter();return {center:[c.lng,c.lat],zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch()};}catch(_){return restoredState.camera||null;}}
function persistState(){
  try{
    const riverOrders={};document.querySelectorAll('.river-order-toggle').forEach(x=>riverOrders[x.dataset.order]=x.checked);
    sessionStorage.setItem(APP_STATE_KEY,JSON.stringify({
      points:points.map(p=>({point_id:p.point_id,lon:p.lon,lat:p.lat,source:p.source,label:p.label})),
      nameDrafts:Object.fromEntries(points.map(p=>[p.point_id,pointNameDraft(p.point_id)])),
      pointColors:{...POINT_COLORS},sidebarCollapsed,currentBasemap,selectedLightBasemap,activePointId,pointInputMode,multiPointMode:pointInputMode==='multi',language:uiLanguage,decimalSeparator,camera:getCameraState(),
      controls:{snapRadius:snapRadiusEl?.value,boundaryMatch:boundaryMatchEl?.value,showHillshade:$('showHillshade')?.checked,hillshadeOpacity:$('hillshadeOpacity')?.value,showBasins:$('showBasins')?.checked,showBasinLabels:$('showBasinLabels')?.checked,showRivers:$('showRivers')?.checked,autoRiverZoom:$('autoRiverZoom')?.checked,riverOrders,showRiverLabels:$('showRiverLabels')?.checked,showHatch:$('showHatch')?.checked,hatchOpacity:$('hatchOpacity')?.value,lineWidth:$('lineWidth')?.value,basinColor:$('basinColor')?.value,riverColor:$('riverColor')?.value}
    }));
  }catch(_){}
}
restorePreferenceControls();

function schedulePersistState(delay=120){
  clearTimeout(persistTimer);
  persistTimer=setTimeout(()=>persistState(),delay);
}

function refreshIcons(){ if(window.lucide) window.lucide.createIcons({attrs:{'stroke-width':2}}); }
function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function clampPointName(value){
  return String(value??'').trim().slice(0,POINT_NAME_MAX_LENGTH);
}
function showPointNameLimitWarning(input){
  const warning=input?.closest('label')?.querySelector('.point-name-limit-warning');
  if(warning){
    warning.classList.remove('hidden');
    clearTimeout(warning._hideTimer);
    warning._hideTimer=setTimeout(()=>warning.classList.add('hidden'),2200);
  }
  showAppToast(`Nama titik maksimal ${POINT_NAME_MAX_LENGTH} karakter.`);
}
function bindPointNameLimit(input){
  if(!input||input.dataset.pointNameLimitBound==='1')return;
  input.dataset.pointNameLimitBound='1';
  input.maxLength=POINT_NAME_MAX_LENGTH;
  input.addEventListener('beforeinput',event=>{
    const type=String(event.inputType||'');
    if(!type.startsWith('insert'))return;
    const start=Number.isFinite(input.selectionStart)?input.selectionStart:input.value.length;
    const end=Number.isFinite(input.selectionEnd)?input.selectionEnd:start;
    const inserted=event.data??'';
    if(type==='insertFromPaste'&&!inserted)return;
    const nextLength=input.value.length-(end-start)+inserted.length;
    if(nextLength>POINT_NAME_MAX_LENGTH){
      event.preventDefault();
      showPointNameLimitWarning(input);
    }
  });
  input.addEventListener('paste',event=>{
    const pasted=event.clipboardData?.getData('text')||'';
    if(!pasted)return;
    const start=Number.isFinite(input.selectionStart)?input.selectionStart:input.value.length;
    const end=Number.isFinite(input.selectionEnd)?input.selectionEnd:start;
    const available=POINT_NAME_MAX_LENGTH-(input.value.length-(end-start));
    if(pasted.length>available){
      event.preventDefault();
      if(available>0){
        input.setRangeText(pasted.slice(0,available),start,end,'end');
        input.dispatchEvent(new Event('input',{bubbles:true}));
      }
      showPointNameLimitWarning(input);
    }
  });
}
function riverNameForUi(value){
  let text=String(value??'').trim();
  if(!text)return '—';
  text=text.replace(/^(?:Kali|K\.|K|Sungai|S\.|S)\s+/i,'').trim();
  return text?`Kali ${text}`:'—';
}
function dtaAnalysisDisplayLabel(id){
  const result=pointResult(id),river=riverNameForUi(result?.official_river?.name),point=String(pointName(id)||id).trim();
  return river&&river!=='—'?`${river} – ${point}`:point;
}
window.dtaAnalysisDisplayLabel=dtaAnalysisDisplayLabel;
function readableTextColor(hex){
  const m=String(hex||'').trim().match(/^#?([0-9a-f]{6})$/i);if(!m)return '#fff';
  const n=parseInt(m[1],16),r=(n>>16)&255,g=(n>>8)&255,b=n&255;
  const luminance=(0.299*r+0.587*g+0.114*b)/255;
  return luminance>.66?'#17233b':'#fff';
}
function emptyFC(){return {type:'FeatureCollection',features:[]};}
function setStatus(text,kind='neutral'){statusEl.textContent=text;statusEl.className=`status ${kind}`;}
function hasOpenSidebarCard(){return Boolean(pointListEl?.querySelector?.('.point-card[open]'));}
function clearActivePointIfNoOpenCard(){
  if(hasOpenSidebarCard()||pointPopup)return;
  activePointId=null;
  applyDtaHighlight();
  schedulePersistState();
}
function setLayerVisibility(id,show){if(map.getLayer(id))map.setLayoutProperty(id,'visibility',show?'visible':'none');}
function parseApiError(payload,fallback='Proses gagal.'){const d=payload?.detail;if(d&&typeof d==='object')return d;return {message:typeof d==='string'?d:fallback};}
async function parseErrorResponse(response,fallback='Proses gagal.'){
  const contentType=(response.headers.get('content-type')||'').toLowerCase();
  if(contentType.includes('application/json')){
    try{return parseApiError(await response.json(),fallback);}catch(_){}
  }
  try{
    const text=(await response.text()).trim();
    if(text&&!/^internal server error$/i.test(text))return {message:text};
  }catch(_){}
  return {message:`${fallback} Server mengembalikan HTTP ${response.status}.`};
}
function pointName(id){const p=points.find(x=>x.point_id===id);return p?.label?.trim()||id;}
function pointNameDraft(id){return pointNameDrafts.has(id)?String(pointNameDrafts.get(id)):pointName(id);}
function pointNameDirty(id){return pointNameDraft(id).trim()!==pointName(id).trim();}
function pointNameState(id){return pointNameSaving.has(id)?'saving':(pointNameDirty(id)?'dirty':'saved');}
function setPointNameDraft(id,value,{persist=true}={}){
  if(!points.some(p=>p.point_id===id))return;
  const raw=String(value??'');
  pointNameDrafts.set(id,raw.slice(0,POINT_NAME_MAX_LENGTH));
  syncPointNameEditors(id);
  if(persist)schedulePersistState();
}
function resetPointNameDraft(id){pointNameDrafts.set(id,pointName(id));syncPointNameEditors(id);schedulePersistState();}
function syncPointNameEditors(id){
  const state=pointNameState(id),draft=pointNameDraft(id),saved=pointName(id);
  document.querySelectorAll(`.rename-point[data-id="${id}"], .popup-rename-point[data-id="${id}"]`).forEach(input=>{
    if(document.activeElement!==input&&input.value!==draft)input.value=draft;
    input.classList.toggle('is-dirty',state==='dirty');
    input.dataset.savedValue=saved;
  });
  document.querySelectorAll(`.point-name-editor[data-id="${id}"], .popup-point-name-editor[data-id="${id}"]`).forEach(editor=>{
    editor.classList.toggle('is-dirty',state==='dirty');
    editor.classList.toggle('is-saving',state==='saving');
    const badge=editor.querySelector('.point-name-state');
    if(badge){badge.textContent=state==='saving'?'Menyimpan...':(state==='dirty'?'Belum disimpan':'');badge.classList.toggle('hidden',state==='saved');}
    const btn=editor.querySelector('.save-name,.popup-save-name');
    if(btn){btn.disabled=state!=='dirty';btn.innerHTML=state==='saving'?'<i data-lucide="loader-circle" class="spin-icon"></i>':'<i data-lucide="save"></i>';}
  });
  const popup=pointPopup?.getElement?.();
  const menu=popup?.querySelector(`.existing-point-menu[data-point-id="${id}"]`);
  if(menu){const title=menu.querySelector('[data-point-saved-title]');if(title)title.textContent=saved;}
  refreshIcons();
}
async function savePointName(id){
  const point=points.find(p=>p.point_id===id);if(!point||pointNameSaving.has(id))return;
  const normalized=pointNameDraft(id).trim();
  if(!normalized){showAppToast('Nama titik tidak boleh kosong.');return;}
  if(normalized.length>POINT_NAME_MAX_LENGTH){showAppToast(`Nama titik maksimal ${POINT_NAME_MAX_LENGTH} karakter.`);return;}
  if(normalized===pointName(id).trim()){resetPointNameDraft(id);return;}
  pointNameSaving.add(id);syncPointNameEditors(id);
  await new Promise(resolve=>setTimeout(resolve,80));
  const current=points.find(p=>p.point_id===id);if(!current){pointNameSaving.delete(id);return;}
  current.label=normalized;const result=pointResult(id);if(result)result.label=normalized;
  pointNameDrafts.set(id,normalized);pointNameSaving.delete(id);
  renderRequestedPoints();renderPointCards();syncPointNameEditors(id);persistState();showAppToast('Nama titik disimpan.');
}
function renderSidebarDtaActions(id,coordinateText){
  return DTA_ACTIONS.map(action=>`<button class="small-icon-btn dta-action-button ${action.sidebarClass}${action.destructive?' danger-icon-btn':''}" data-id="${id}" ${action.id==='copyCoordinate'?`data-coordinate="${escapeHtml(coordinateText)}"`:''} aria-label="${escapeHtml(action.label)}"><i data-lucide="${action.icon}"></i><span>${escapeHtml(action.label)}</span></button>`).join('');
}
function renderPopupDtaActions(){
  return DTA_ACTIONS.map(action=>`<button type="button" class="${action.destructive?'danger':''}" data-action="${action.id}"><i data-lucide="${action.icon}"></i><span>${escapeHtml(action.label)}</span></button>`).join('');
}
function nextPointId(){for(let i=1;i<=MAX_POINTS;i++){const id=`O${i}`;if(!points.some(p=>p.point_id===id))return id;}return null;}
function formatArea(value){
  const v=Number(value)||0;
  return formatDisplayNumber(v,v<10?2:(v<100?1:0));
}
function formatDisplayNumber(value){
  if(!Number.isFinite(Number(value)))return '—';
  const abs=Math.abs(Number(value)),digits=abs<1?3:(abs<10?2:(abs<100?1:0));
  const raw=Number(value).toLocaleString('en-US',{maximumFractionDigits:digits,minimumFractionDigits:0});
  return decimalSeparator===','?raw.replace(/,/g,'X').replace(/\./g,',').replace(/X/g,'.'):raw;
}
function applyAnalysisLanguage(){
  if(uiLanguage!=='en')return;
  const content=$('hydrologicAnalysisContent');if(!content?.innerHTML)return;
  const replacements={
    'RESPONS HIDROLOGI DTA':'DTA HYDROLOGIC RESPONSE','Indikator Kuantitatif Kunci':'Key Quantitative Indicators','Ringkasan untuk pengambilan keputusan':'Decision-making summary','Lihat Analisis Teknis':'View Technical Analysis','Topografi & Bentuk DTA':'Terrain & Basin Morphometry','Jaringan Drainase':'Drainage Network','Parameter Lintasan Aliran':'Flowpath Parameters','Penutupan Lahan':'Land Cover','Curve Number dan Potensi Limpasan':'Curve Number & Runoff Potential','Curve Number dan Potensi Limpasan':'Curve Number & Runoff Potential','Curve Number (CN)':'Curve Number (CN)','Orde sungai maksimum':'Maximum stream order','Tc Representatif':'Representative multi-method Tc','Waktu Konsentrasi':'Time of Concentration','Batasan interpretasi':'Interpretation limitations','Luas DTA':'Basin area','Rata-rata kemiringan':'Mean slope','Relief DTA (R)':'Basin relief (R)','Rentang elevasi (ΔZ)':'Elevation range (ΔZ)','Kesepakatan antar-metode':'Inter-method agreement','Kerapatan drainase':'Drainage density','Faktor bentuk':'Form factor','Lintasan aliran terpanjang':'Longest flow path','CN-II tertimbang':'Weighted CN-II','Keliling':'Perimeter','Elevasi minimum':'Minimum elevation','Elevasi rata-rata':'Mean elevation','Elevasi maksimum':'Maximum elevation','Elevasi outlet':'Outlet elevation','Rasio elongasi':'Elongation ratio','Rasio kebulatan':'Circularity ratio','Rasio relief':'Relief ratio','Integral hipsometrik':'Hypsometric integral','Panjang total sungai':'Total stream length','Panjang sungai utama':'Main channel length','Kemiringan ruas sungai':'Reach slope','Kemiringan lintasan aliran terpanjang':'Longest flowpath slope','Kemiringan lintasan melalui sentroid':'Centroidal flowpath slope','Kemiringan lintasan 10-85':'10-85 flowpath slope','Distribusi Kelas Lereng':'Slope Class Distribution','Klasifikasi':'Interpretation','Implikasi':'Definition','Nilai':'Value','Parameter':'Parameter','Definisi':'Definition','Keterangan':'Notes','Rekomendasi':'Recommended'
  };
  let html=content.innerHTML;for(const [id,en] of Object.entries(replacements))html=html.replaceAll(id,en);content.innerHTML=html;refreshIcons(content);
}
function applyInterfaceLanguage(){
  const en=uiLanguage==='en';
  document.documentElement.lang=en?'en':'id';
  if(en){
    const translated={
      'ANALISIS SPASIAL':'SPATIAL ANALYSIS','Istilah & Definisi':'Terms & Definitions','Metodologi & Sumber Data':'Methodology & Data Sources',
      'Pilih Titik':'Select Point','Mode satu titik':'Single-point mode','Bahasa':'Language','Pemisah desimal':'Decimal separator',
      'Pengaturan lanjutan':'Advanced settings','Pencarian sungai terdekat':'Nearest-stream search','Jarak penyesuaian batas DAS':'Basin-boundary adjustment distance',
      'Hasil DTA':'DTA Results','Maksimal 10 DTA per pemrosesan':'Maximum 10 DTAs per run','Fokus Semua':'Focus All','Hapus Semua':'Clear All',
      'Hubungan Antar Titik':'Relationships Between Points','Peta Dasar':'Basemap','Layer & Tampilan':'Layers & Display','Penggaris':'Measure',
      'Warna DTA':'DTA Color','Pilih warna':'Choose color','KODE HEX warna DTA':'DTA color HEX code','Opasitas':'Opacity','Batas DAS':'Basin Boundary',
      'Nama DAS':'Basin labels','Jaringan Sungai':'River Network','Otomatis sesuai zoom':'Auto by zoom','Label sungai':'River labels',
      'DTA hasil delineasi':'Delineated DTA','Arsiran':'Hatching','Ketebalan garis':'Line width','Reset':'Reset','Koma (,)':'Comma (,)','Titik (.)':'Dot (.)',
      'Unduh Hasil':'Download Result','Analisis Morfometri':'Morphometric Analysis','Belum ada hasil delineasi.':'No delineation result yet.',
      'Mode Satu Titik. Tekan Mulai Tambah untuk memilih outlet.':'Single-point mode. Press Start Adding Point to select an outlet.'
    };
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    const nodes=[];let node;while((node=walker.nextNode())){if(!['SCRIPT','STYLE'].includes(node.parentElement?.tagName))nodes.push(node);}
    nodes.forEach(item=>{let value=item.nodeValue;Object.entries(translated).forEach(([id,valueEn])=>{value=value.replaceAll(id,valueEn);});item.nodeValue=value;});
  }
  const button=(id,icon,value)=>{const el=$(id);if(el)el.innerHTML=`<i data-lucide="${icon}"></i>${value}`;};
  button('previewCoordinateBtn','map-pin',en?'Show Point':'Tampilkan Titik');
  button('downloadBtn','download',en?'Download Result':'Unduh Hasil');
  button('addPointSessionBtn','crosshair',en?'Start Adding Point':'Mulai Tambah');
  button('pointModeBtn','map-pin',pointInputMode==='multi'?(en?'Multiple Points':'Multi Titik'):(en?'Single Point':'Satu Titik'));
  const select=$('languageSelect');if(select)select.value=uiLanguage;
  const decimal=$('decimalSeparatorSelect');if(decimal)decimal.value=decimalSeparator;
  renderPointCards();refreshIcons();
}
function formatAnalysisValue(value,{digits=2,unit=''}={}){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return `<span class="analysis-na">—</span>`;
  return `${formatDisplayNumber(value,digits)}${unit?` ${unit}`:''}`;
}
function analysisMetric(label,value,options={}){
  const tooltip=options.tooltip?String(options.tooltip):'';
  const help=tooltip?` data-help="${escapeHtml(tooltip)}"`:'';
  const info=tooltip?`<button class="info-tooltip analysis-metric-info" type="button" aria-label="Informasi ${escapeHtml(label)}">i</button>`:'';
  return `<div class="analysis-metric${options.priorityAccent?' analysis-metric--priority':''}"${help}><span class="analysis-metric-label"><span>${escapeHtml(label)}</span>${info}</span><strong>${formatAnalysisValue(value,options)}</strong>${options.interpretation?`<small>${escapeHtml(options.interpretation)}</small>`:''}</div>`;
}
function analysisIndicatorTooltip(label,value,{tc={}}={}){
  const hasValue=value!==null&&value!==undefined&&Number.isFinite(Number(value));
  if(!hasValue)return 'Dasar interpretasi: indikator belum dapat dinilai karena data belum tersedia. Tingkat kepercayaan: Rendah.';
  const tcAgreement=String(tc.method_agreement||tc.confidence||'belum dinilai');
  const meta={
    'Luas DTA (A)':'Dasar interpretasi: luas geometri DTA hasil delineasi; tidak digunakan sebagai kelas cepat/lambat secara tunggal. Tingkat kepercayaan: Tinggi, dihitung langsung dari geometri DTA.',
    'Kemiringan rata-rata (S)':'Dasar interpretasi: Datar 0–8%, Landai >8–15%, Agak curam >15–25%, Curam >25–40%, dan Sangat curam >40%. Tingkat kepercayaan: Tinggi, dihitung dari data ketinggian.',
    'Relief DTA (R)':'Dasar interpretasi: selisih elevasi batas tertinggi terhadap elevasi outlet; tidak diberi kelas respons tunggal. Tingkat kepercayaan: Tinggi, dihitung dari data ketinggian dan posisi outlet.',
    'Kerapatan drainase (Dd)':'Dasar interpretasi: Rendah <1,0; Sedang 1,0–<2,0; Tinggi 2,0–<3,5; Sangat tinggi ≥3,5 km/km². Tingkat kepercayaan: Sedang–tinggi, bergantung pada kelengkapan dan skala jaringan sungai.',
    'Frekuensi sungai (Fs)':'Dasar interpretasi: jumlah sungai Strahler per km²; tidak diterapkan ambang universal karena sensitif terhadap skala dan detail jaringan. Tingkat kepercayaan: Sedang, bergantung pada kelengkapan jaringan sungai.',
    'Orde sungai maksimum':'Dasar interpretasi: orde Strahler tertinggi pada jaringan sungai di dalam DTA. Tingkat kepercayaan: Sedang, bergantung pada kelengkapan dan konsistensi jaringan sungai.',
    'Faktor bentuk (Ff)':'Dasar interpretasi: Sangat memanjang <0,30; Memanjang 0,30–<0,50; Agak kompak 0,50–<0,75; Kompak ≥0,75. Tingkat kepercayaan: Tinggi, dihitung dari luas dan panjang karakteristik DTA.',
    'Lintasan aliran terpanjang (Lb)':'Dasar interpretasi: panjang lintasan hidrologis terpanjang menuju outlet; tidak digunakan dengan ambang universal. Tingkat kepercayaan: Sedang–tinggi, bergantung pada data ketinggian dan konektivitas lintasan aliran.',
    'Kemiringan alur utama (Sc)':'Dasar interpretasi: beda elevasi ujung alur utama terhadap outlet dibagi panjang alur utama; tidak digunakan dengan ambang universal. Tingkat kepercayaan: Sedang–tinggi, bergantung pada data ketinggian dan representasi alur utama.',
    'Curve Number (CN)':'Dasar interpretasi: nilai CN-II tertimbang; semakin tinggi CN, semakin kecil potensi retensi dan semakin besar kecenderungan limpasan. Tingkat kepercayaan: Sedang, dipengaruhi ketelitian penutupan lahan serta kelompok tanah hidrologi.',
    'Waktu konsentrasi (Tc)':`Dasar interpretasi: nilai representatif dari beberapa metode waktu konsentrasi yang tersedia. Tingkat kepercayaan: ${tcAgreement}; menunjukkan kesepakatan antar-metode, bukan ukuran kepercayaan statistik.`,
    'Kawasan terbangun':'Dasar interpretasi: persentase area kelas penutupan lahan terbangun di dalam DTA; tidak diterapkan ambang universal. Tingkat kepercayaan: Sedang, mengikuti resolusi dan akurasi penutupan lahan.'
  };
  return meta[label]||'Dasar interpretasi mengikuti definisi parameter pada Karakteristik Detail. Tingkat kepercayaan mengikuti ketersediaan dan kualitas data sumber.';
}
function analysisResponseTheme(responseClass){
  const normalized=String(responseClass||'').trim().toLowerCase().replace(/[–—-]/g,'-').replace(/\s+/g,' ');
  const themes={
    'lambat':{key:'slow',primary:'#4776A8',tint:'#EEF4FA',stronger:'#3B628C'},
    'lambat-sedang':{key:'slow-medium',primary:'#4F8585',tint:'#EDF5F4',stronger:'#3E6F70'},
    'sedang':{key:'medium',primary:'#A58A45',tint:'#F7F3E7',stronger:'#806A2E'},
    'sedang-cepat':{key:'medium-fast',primary:'#D47A3A',tint:'#FBF0E7',stronger:'#A95C29'},
    'cepat':{key:'fast',primary:'#C65353',tint:'#FAECEC',stronger:'#9D3F3F'},
  };
  return themes[normalized]||themes.sedang;
}
function technicalRow(label,value,classification='—',implication='—',options={}){
  const classificationText=classification==='—'||classification==='-'||classification==null?'':String(classification);
  return `<tr><th>${escapeHtml(label)}</th><td>${formatAnalysisValue(value,options)}</td><td>${escapeHtml(classificationText)}</td><td class="narrative-cell">${escapeHtml(implication||'—')}</td></tr>`;
}
function technicalTextRow(label,value,classification='—',implication='—'){
  const classificationText=classification==='—'||classification==='-'||classification==null?'':String(classification);
  return `<tr><th>${escapeHtml(label)}</th><td>${value?escapeHtml(value):'<span class="analysis-na">Belum tersedia</span>'}</td><td>${escapeHtml(classificationText)}</td><td class="narrative-cell">${escapeHtml(implication||'—')}</td></tr>`;
}
function formatNarrativeText(value){
  const separator=decimalSeparator==='.'?'.':',';
  return String(value||'').replace(/(\d)[,.](\d)/g,`$1${separator}$2`);
}
const hydrologicAnalysisPromises=new Map();
function startAnalysisProgress(target,label='Menghitung karakteristik DTA…'){
  if(!target)return {complete(){},fail(){}};
  const steps=[1,5,10,20,30,45,60,75,85,92],state={index:0,timer:null,raf:null,spinStart:null,done:false};
  target.innerHTML=`<div class="analysis-loading"><div class="analysis-loading-head"><span class="analysis-spinner" aria-hidden="true"></span><div><strong>${escapeHtml(label)}</strong><span class="analysis-progress-value">1%</span></div></div><div class="analysis-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="1"><i style="width:1%"></i></div></div>`;
  const bar=target.querySelector('.analysis-progress-track'),fill=bar?.querySelector('i'),value=target.querySelector('.analysis-progress-value'),spinner=target.querySelector('.analysis-spinner');
  const set=valueNow=>{const valueSafe=Math.max(0,Math.min(100,Number(valueNow)||0));if(fill)fill.style.width=`${valueSafe}%`;if(value)value.textContent=`${Math.round(valueSafe)}%`;bar?.setAttribute('aria-valuenow',String(Math.round(valueSafe)));};
  const spin=timestamp=>{
    if(state.done||!spinner?.isConnected)return;
    if(state.spinStart==null)state.spinStart=timestamp;
    const angle=((timestamp-state.spinStart)*0.32)%360;
    spinner.style.transform=`rotate(${angle}deg)`;
    state.raf=requestAnimationFrame(spin);
  };
  if(spinner&&typeof requestAnimationFrame==='function')state.raf=requestAnimationFrame(spin);
  state.timer=setInterval(()=>{if(state.index>=steps.length-1)return;state.index+=1;set(steps[state.index]);},140);
  const stop=()=>{state.done=true;if(state.timer){clearInterval(state.timer);state.timer=null;}if(state.raf!=null&&typeof cancelAnimationFrame==='function'){cancelAnimationFrame(state.raf);state.raf=null;}};
  return {
    complete(){stop();set(100);},
    fail(){stop();},
  };
}
window.startAnalysisProgress=startAnalysisProgress;
async function ensureHydrologicAnalysis(id){
  const result=pointResult(id);
  if(!result)throw new Error('Hasil DTA tidak ditemukan.');
  if(result.hydrologic_analysis)return result.hydrologic_analysis;
  if(hydrologicAnalysisPromises.has(id))return hydrologicAnalysisPromises.get(id);
  const promise=(async()=>{
    const response=await fetch('/api/characteristics',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({point_result:result,decimal_separator:decimalSeparator})});
    const payload=await response.json();
    if(!response.ok)throw new Error(payload?.detail||'Perhitungan karakteristik DTA gagal.');
    result.hydrologic_analysis=payload;
    return payload;
  })().finally(()=>hydrologicAnalysisPromises.delete(id));
  hydrologicAnalysisPromises.set(id,promise);
  return promise;
}
window.ensureHydrologicAnalysis=ensureHydrologicAnalysis;
async function openHydrologicAnalysis(id){
  const result=pointResult(id);let analysis=result?.hydrologic_analysis;
  if(!result){showAppToast('Hasil DTA tidak ditemukan.');return;}
  if(!analysis){
    $('hydrologicAnalysisTitle').textContent=dtaAnalysisDisplayLabel(id);
    openMapModal($('hydrologicAnalysisModal'));
    const progress=startAnalysisProgress($('hydrologicAnalysisContent'),'Menghitung karakteristik DTA…');
    try{analysis=await ensureHydrologicAnalysis(id);progress.complete();await new Promise(resolve=>setTimeout(resolve,90));}catch(error){progress.fail();$('hydrologicAnalysisContent').innerHTML=`<div class="analysis-data-note"><i data-lucide="triangle-alert"></i><span>${escapeHtml(error?.message||String(error))}</span></div>`;refreshIcons($('hydrologicAnalysisModal'));return;}
  }
  const morph=analysis.morphometry||{},terrain=analysis.terrain||{},elev=terrain.elevation||{},slope=terrain.slope||{},drain=analysis.drainage||{},landcover=analysis.landcover||{},landsystem=analysis.landsystem||{},cn=analysis.curve_number||{},tc=analysis.time_of_concentration||{},flowSlope=terrain.flowpath_slope||{},keys=analysis.key_indicators||{},classes=analysis.classifications||{},summary=analysis.executive_summary||{};
  const rbByOrder=Object.entries(drain.bifurcation_ratios_by_order||{}).map(([pair,value])=>`${pair.replace('-', '→')}: ${formatDisplayNumber(value,2)}`).join('; ');
  const responseTheme=analysisResponseTheme(summary.response_class);
  const modal=$('hydrologicAnalysisModal');
  modal.dataset.responseTheme=responseTheme.key;
  modal.style.setProperty('--analysis-status-primary',responseTheme.primary);
  modal.style.setProperty('--analysis-status-tint',responseTheme.tint);
  modal.style.setProperty('--analysis-status-stronger',responseTheme.stronger);
  $('hydrologicAnalysisTitle').textContent=dtaAnalysisDisplayLabel(id);
  const slopeRanges={'Datar':'Datar (0–8%)','Landai':'Landai (>8–15%)','Agak curam':'Agak curam (>15–25%)','Curam':'Curam (>25–40%)','Sangat curam':'Sangat curam (>40%)'};
  const slopeBars=(slope.distribution||[]).map(item=>`<div class="slope-class-row"><span>${escapeHtml(slopeRanges[item.class]||item.class)}</span><div><i style="width:${Math.max(0,Math.min(100,Number(item.area_pct)||0))}%"></i></div><strong>${formatAnalysisValue(item.area_pct,{digits:1,unit:'%'})}</strong></div>`).join('');
  const priorityIndicatorLabels=new Set(['Kemiringan rata-rata (S)','Kerapatan drainase (Dd)','Curve Number (CN)','Waktu konsentrasi (Tc)']);
  const indicatorItems=(analysis.key_indicator_items||[]).map(item=>analysisMetric(item.label,item.value,{
    unit:item.unit||'',
    priorityAccent:priorityIndicatorLabels.has(item.label),
    tooltip:analysisIndicatorTooltip(item.label,item.value,{tc})
  })).join('');
  const cnInterpretations=cn.interpretations||{};
  const tcRows=(tc.methods||[]).filter(item=>Number.isFinite(Number(item.value_hours))&&Number(item.value_hours)>0).map(item=>`<tr><th>${escapeHtml(item.label)}</th><td>${formatAnalysisValue(item.value_hours,{unit:'jam'})}</td><td><small class="method-reason">${escapeHtml(item.reason||'—')}</small></td></tr>`).join('');
  const missing=(terrain.missing||[]).length?`<div class="analysis-data-note"><i data-lucide="database-zap"></i><span>Data opsional belum lengkap: ${escapeHtml(terrain.missing.join(', '))}. Lengkapi sumber data agar metrik terkait aktif otomatis.</span></div>`:'';
  const limitations=(analysis.limitations||[]).map(x=>`<li>${escapeHtml(x)}</li>`).join('');
  $('hydrologicAnalysisContent').innerHTML=`
    <section class="analysis-executive"><div><span class="analysis-kicker">RESPONS HIDROLOGI</span><strong>${escapeHtml(String(summary.response_class||'Belum dapat dinilai').toUpperCase())}</strong></div><p>${escapeHtml(formatNarrativeText(summary.narrative||''))}</p></section>
    <section><div class="analysis-section-title"><span>Indikator Kunci</span><small class="analysis-priority-legend"><i></i><span>Oranye = indikator prioritas respons hidrologis</span></small></div><div class="analysis-indicator-grid">
      ${indicatorItems}
    </div>${missing}</section>
    <details class="technical-analysis"><summary><span><i data-lucide="table-properties"></i>Lihat Karakteristik Detail</span><i data-lucide="chevron-down"></i></summary><div id="analysisTechnicalBody" class="technical-analysis-body">
      <div class="technical-group territory-characteristics"><h3>Karakteristik Wilayah</h3><div class="technical-table-wrap territory-table"><table><tbody><tr><td>${(analysis.territory_paragraphs||[analysis.territory_detail]).filter(Boolean).map(paragraph=>`<p>${escapeHtml(formatNarrativeText(paragraph))}</p>`).join('')||'<p>Karakteristik wilayah belum tersedia.</p>'}</td></tr></tbody></table></div></div>
      <div class="technical-group"><h3>Topografi & Bentuk DTA</h3><div class="technical-table-wrap"><table><thead><tr><th>Parameter</th><th>Nilai</th><th>Interpretasi</th><th>Definisi</th></tr></thead><tbody>
        ${technicalRow('Luas DTA (A)',morph.area_km2,'—','Luas wilayah tangkapan pada batas DTA',{digits:2,unit:'km²'})}
        ${technicalRow('Keliling (P)',morph.perimeter_km,'—','Keliling batas DTA yang telah diperhalus',{digits:2,unit:'km'})}
        ${technicalRow('Panjang DTA (Lb)',morph.basin_length_km,'—','Lintasan aliran terpanjang dari outlet ke hulu',{digits:2,unit:'km'})}
        ${technicalRow('Elevasi minimum',elev.min_m,'—','Titik ketinggian terendah dalam DTA',{digits:1,unit:'mdpl'})}
        ${technicalRow('Elevasi rata-rata',elev.mean_m,'—','Rata-rata ketinggian seluruh wilayah DTA',{digits:1,unit:'mdpl'})}
        ${technicalRow('Elevasi maksimum',elev.max_m,'—','Titik ketinggian tertinggi dalam DTA',{digits:1,unit:'mdpl'})}
        ${technicalRow('Elevasi outlet',elev.outlet_m,'—','Ketinggian pada titik outlet DTA',{digits:1,unit:'mdpl'})}
        ${technicalRow('Elevasi batas tertinggi',elev.divide_max_m,'—','Titik tertinggi sepanjang batas DTA',{digits:1,unit:'mdpl'})}
        ${technicalRow('Relief DTA (R)',elev.relief_m,Number.isFinite(Number(elev.relief_m))?(elev.relief_m>=1000?'Tinggi':'—'):'—','Selisih batas tertinggi terhadap elevasi outlet',{digits:1,unit:'m'})}
        ${technicalRow('Rentang elevasi (ΔZ)',elev.elevation_range_m,'—','Selisih elevasi maksimum dan minimum DTA',{digits:1,unit:'m'})}
        ${technicalRow('Kemiringan rata-rata (S)',slope.mean_pct,classes.mean_slope,'Rata-rata kemiringan permukaan seluruh DTA',{digits:2,unit:'%'})}
        ${technicalRow('Kemiringan maksimum',slope.p95_pct,'—','Nilai tinggi representatif kemiringan permukaan DTA',{digits:2,unit:'%'})}
        ${technicalTextRow('Arah lereng dominan',terrain.aspect?.dominant,'Orientasi','Arah lereng yang paling banyak dijumpai')}
        ${technicalRow('Faktor bentuk (Ff)',morph.form_factor,classes.shape,'Perbandingan luas terhadap kuadrat panjang DTA',{digits:3})}
        ${technicalRow('Rasio elongasi (Re)',morph.elongation_ratio,classes.elongation,'Perbandingan diameter setara terhadap panjang DTA',{digits:3})}
        ${technicalRow('Rasio kebulatan (Rc)',morph.circularity_ratio,Number.isFinite(Number(morph.circularity_ratio))?(morph.circularity_ratio>=.5?'Relatif membulat':'Relatif tidak membulat'):'—','Luas dibandingkan dengan kuadrat keliling DTA',{digits:3})}
        ${technicalRow('Rasio relief',morph.relief_ratio,'—','Relief dibagi panjang DTA',{digits:4})}
        ${technicalRow('Integral hipsometrik (HI)',terrain.hypsometry?.integral,terrain.hypsometry?.stage||'—','Tahap perkembangan bentuk lahan berdasarkan distribusi elevasi',{digits:3})}
      </tbody></table></div></div>
      <div class="technical-group"><h3>Jaringan Drainase</h3><div class="technical-table-wrap"><table><thead><tr><th>Parameter</th><th>Nilai</th><th>Interpretasi</th><th>Definisi</th></tr></thead><tbody>
        ${technicalRow('Panjang total sungai',drain.total_stream_length_km,'—','Jumlah panjang seluruh sungai dalam DTA',{digits:2,unit:'km'})}
        ${technicalRow('Panjang sungai utama',drain.main_channel_length_km,'—','Panjang jalur sungai utama menuju outlet',{digits:2,unit:'km'})}
        ${technicalRow('Lintasan aliran terpanjang',terrain.longest_flow_path_km,'—','Jarak aliran terpanjang dari outlet ke hulu',{digits:2,unit:'km'})}
        ${technicalRow('Kemiringan alur utama',drain.main_channel_slope_pct,'—','Beda elevasi dibagi panjang alur utama',{digits:3,unit:'%'})}
        ${technicalRow('Kemiringan rata-rata jaringan',drain.network_mean_slope_pct,'—','Rata-rata kemiringan ruas berbobot panjang',{digits:3,unit:'%'})}
        ${technicalRow('Sinuositas alur utama',drain.channel_sinuosity,'—','Panjang alur dibagi jarak lurus ujungnya',{digits:3})}
        ${technicalRow('Jumlah percabangan',drain.junction_count,'—','Titik pertemuan sedikitnya dua ruas sungai',{digits:0})}
        ${technicalRow('Kerapatan percabangan',drain.junction_density_per_km2,'—','Jumlah percabangan per luas DTA',{digits:3,unit:'percabangan/km²'})}
        ${technicalRow('Intensitas drainase (Id)',drain.drainage_intensity,'—','Frekuensi sungai dibagi kerapatan drainase',{digits:3})}
        ${technicalRow('Nomor infiltrasi (If)',drain.infiltration_number,'—','Kerapatan drainase dikali frekuensi sungai',{digits:3})}
        ${technicalRow('Orde sungai maksimum (Strahler)',drain.stream_order_max,'—','Orde Strahler tertinggi dalam DTA',{digits:0})}
        ${technicalRow('Kerapatan drainase (Dd)',drain.drainage_density_km_per_km2,classes.drainage_density,'Panjang sungai per luas DTA',{digits:3,unit:'km/km²'})}
        ${technicalRow('Frekuensi sungai (Fs)',drain.stream_frequency_per_km2,'—','Jumlah sungai Strahler per luas DTA',{digits:3,unit:'sungai/km²'})}
        ${technicalRow('Rasio percabangan (Rb)',drain.bifurcation_ratio,'—','Rata-rata rasio jumlah sungai antar orde berurutan',{digits:3})}
        ${Object.entries(drain.bifurcation_ratios_by_order||{}).map(([pair,value])=>{const order=String(pair).split('-')[0];return technicalRow(`Rasio percabangan orde ${order}`,value,'—',`Perbandingan jumlah sungai orde ${order} terhadap orde berikutnya`,{digits:3});}).join('')}
      </tbody></table></div></div>
      <div class="technical-group"><h3>Parameter Lintasan Aliran</h3><div class="technical-table-wrap"><table><thead><tr><th>Parameter</th><th>Nilai</th><th>Interpretasi</th><th>Definisi</th></tr></thead><tbody>
        ${technicalRow('Panjang lintasan aliran (L)',terrain.longest_flow_path_km,'—','Jarak aliran terpanjang dari outlet ke hulu',{digits:3,unit:'km'})}
        ${technicalRow('Panjang lintasan aliran melalui sentroid (Lca)',terrain.centroidal_flowpath_km,'—','Jarak outlet ke titik lintasan terdekat sentroid',{digits:3,unit:'km'})}
        ${technicalRow('Panjang lintasan aliran 10-85 (L10-85)',terrain.flowpath_10_85_km,'—','Bagian lintasan antara posisi 10% dan 85%',{digits:3,unit:'km'})}
        ${technicalRow('Kemiringan lintasan aliran terpanjang (SL)',flowSlope.longest_flowpath_pct,'—','Beda elevasi dibagi panjang lintasan terpanjang',{digits:3,unit:'%'})}
        ${technicalRow('Kemiringan lintasan melalui sentroid (Sca)',flowSlope.centroidal_flowpath_pct,'—','Beda elevasi dibagi panjang lintasan melalui sentroid',{digits:3,unit:'%'})}
        ${technicalRow('Kemiringan lintasan 10-85 (S10-85)',flowSlope.flowpath_10_85_pct,'—','Beda elevasi dibagi panjang lintasan 10–85',{digits:3,unit:'%'})}
      </tbody></table></div></div>
      <div class="technical-group landcover-group"><h3>Penutupan Lahan</h3><div class="technical-table-wrap"><table><thead><tr><th>Kode PL</th><th>Kelas</th><th>Luas</th><th>Persentase area</th></tr></thead><tbody>
        ${(landcover.classes||[]).map(item=>`<tr><th>${escapeHtml(item.code)}</th><td>${escapeHtml(item.name)}</td><td>${formatAnalysisValue(item.area_km2,{unit:'km²'})}</td><td>${formatAnalysisValue(item.area_pct,{unit:'%'})}</td></tr>`).join('')||'<tr><td colspan="4">Data penutup/penggunaan lahan belum tersedia.</td></tr>'}
      </tbody></table></div></div>
      <div class="technical-group cn-group"><h3>Curve Number dan Potensi Limpasan</h3><div class="analysis-indicator-grid cn-summary-grid">
        ${analysisMetric('Curve Number Rata-rata Tertimbang (CN-II)',cn.weighted_cn_ii,{interpretation:cnInterpretations.weighted_cn})}${analysisMetric('Retensi Potensial (S)',cn.potential_retention_mm,{unit:'mm',interpretation:cnInterpretations.retention})}${analysisMetric('Area CN ≥ 80',cn.high_cn_pct,{unit:'%',interpretation:cnInterpretations.high_cn_area})}
      </div><h4 class="analysis-distribution-title">Distribusi Curve Number</h4><div class="slope-class-list analysis-distribution-list">${(cn.distribution||[]).map(item=>`<div class="slope-class-row"><span>${escapeHtml(item.class)}</span><div><i style="width:${Math.max(0,Math.min(100,Number(item.area_pct)||0))}%"></i></div><strong>${formatAnalysisValue(item.area_pct,{digits:1,unit:'%'})}</strong></div>`).join('')}</div></div>
      <div class="technical-group landsystem-group"><h3>Sistem Lahan</h3><div class="technical-table-wrap"><table><thead><tr><th>Tipe sistem lahan</th><th>Fisiografi</th><th>Relief</th><th>Luas</th><th>Persentase</th></tr></thead><tbody>${(landsystem.classes||[]).map(item=>`<tr><th>${escapeHtml(item.land_type||item.name)}</th><td>${escapeHtml(item.physiography||'—')}</td><td>${escapeHtml(item.relief_class||'—')}</td><td>${formatAnalysisValue(item.area_km2,{unit:'km²'})}</td><td>${formatAnalysisValue(item.area_pct,{unit:'%'})}</td></tr>`).join('')||'<tr><td colspan="5">Data sistem lahan belum tersedia.</td></tr>'}</tbody></table></div></div>
      <div class="technical-group tc-group"><h3>Waktu Konsentrasi</h3><div class="technical-table-wrap"><table><thead><tr><th>Metode</th><th>Estimasi</th><th>Keterangan</th></tr></thead><tbody>
        ${tcRows}<tr class="recommendation-row"><th>Tc Representatif</th><td>${formatAnalysisValue(tc.representative_hours??tc.recommended_hours,{unit:'jam'})}</td><td><strong>Dasar: ${escapeHtml((tc.representative_methods||tc.recommendation_methods||[]).join(', ')||'Belum tersedia')}</strong><small class="method-reason">Kesepakatan antar-metode: ${escapeHtml(tc.method_agreement||tc.confidence||'Rendah')}. ${escapeHtml(tc.representative_basis||tc.recommendation_basis||'')}</small></td></tr>
      </tbody></table></div></div>
      ${slopeBars?`<div class="technical-group slope-distribution-group"><h3>Distribusi Kelas Lereng</h3><div class="slope-class-list">${slopeBars}</div></div>`:''}
      <div class="analysis-limitations"><h3>Batasan interpretasi</h3><ul>${limitations}</ul></div>
    </div></details>`;
  const detailBody=$('analysisTechnicalBody'),limitationsEl=detailBody?.querySelector('.analysis-limitations');
  ['.slope-distribution-group','.landcover-group','.landsystem-group','.cn-group','.tc-group'].forEach(selector=>{const section=detailBody?.querySelector(selector);if(section&&limitationsEl)detailBody.insertBefore(section,limitationsEl);});
  refreshIcons($('hydrologicAnalysisModal'));applyAnalysisLanguage();window.HydroUI?.enhanceFieldHelp($('hydrologicAnalysisModal'));openMapModal($('hydrologicAnalysisModal'));
}
function formatDistance(m){const v=Number(m)||0;return v>=1000?`${formatDisplayNumber(v/1000,2)} km`:`${formatDisplayNumber(Math.round(v),0)} m`;}
function haversineMeters(lon1,lat1,lon2,lat2){const R=6371008.8,toRad=Math.PI/180,p1=lat1*toRad,p2=lat2*toRad,dp=(lat2-lat1)*toRad,dl=(lon2-lon1)*toRad;const a=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));}
function nearestExistingPoint(lon,lat,{excludeId=null}={}){let best=null;for(const p of points){if(excludeId&&p.point_id===excludeId)continue;const c=pointMapCoordinate(p.point_id)||{lon:p.lon,lat:p.lat};const d=haversineMeters(lon,lat,c.lon,c.lat);if(!best||d<best.distance_m)best={point:p,distance_m:d};}return best;}
function pointResult(id){return batchResult?.results?.find(r=>r.point_id===id)||null;}
function pointMapCoordinate(id){const p=points.find(x=>x.point_id===id),r=pointResult(id);if(!p)return null;const lon=Number.isFinite(Number(r?.snapped_lon))?Number(r.snapped_lon):Number(p.lon);const lat=Number.isFinite(Number(r?.snapped_lat))?Number(r.snapped_lat):Number(p.lat);return {lon,lat};}
function pointCoordinateText(id){const c=pointMapCoordinate(id);return c?`${c.lat.toFixed(6)}, ${c.lon.toFixed(6)}`:'';}
function zoomToOutlet(id){const c=pointMapCoordinate(id);if(!c)return;setActivePoint(id,{openCard:false});map.easeTo({center:[c.lon,c.lat],zoom:Math.max(map.getZoom(),15),duration:550});}
function focusPointNameEditor(id){if(sidebarCollapsed)setSidebarCollapsed(false);setActivePoint(id,{openCard:true});setTimeout(()=>{const input=pointListEl.querySelector(`.rename-point[data-id="${id}"]`);input?.focus();input?.select();input?.scrollIntoView({block:'nearest',behavior:'smooth'});},120);}
function focusPointColorEditor(id){if(sidebarCollapsed)setSidebarCollapsed(false);setActivePoint(id,{openCard:true});setTimeout(()=>{const btn=pointListEl.querySelector(`.change-point-color[data-id="${id}"]`);btn?.scrollIntoView({block:'nearest',behavior:'smooth'});if(btn)openDtaColorPicker(id,btn);},120);}
function cancelScheduledPointPopup(){
  if(mapPointClickTimer){clearTimeout(mapPointClickTimer);mapPointClickTimer=null;}
}
function cancelPointPopupValidation(){
  pointPopupRequestSerial++;
  if(pointPopupAbortController){
    try{pointPopupAbortController.abort();}catch(_){}
    pointPopupAbortController=null;
  }
}
function isExistingPointPopupOpen(){
  return Boolean(pointPopup?.getElement?.()?.classList?.contains('existing-point-popup'));
}
function resetSelectionAfterExistingPopupClose(){
  if(hasOpenSidebarCard()){
    const openCard=pointListEl.querySelector('.point-card[open]');
    activePointId=openCard?.dataset?.pointId||null;
  }else{
    activePointId=null;
  }
  applyDtaHighlight();
  schedulePersistState();
}
function closePointPopup({cancelPending=true}={}){
  if(cancelPending)cancelPointPopupValidation();
  if(pointPopup){const popup=pointPopup;pointPopup=null;try{popup.remove();}catch(_){}}
  clearSnapPreview();
  clearActivePointIfNoOpenCard();
}
function schedulePointPopupFromMap(lon,lat,{moveTargetId=null}={}){
  cancelScheduledPointPopup();
  mapPointClickTimer=setTimeout(()=>{
    mapPointClickTimer=null;
    openPointPopup(lon,lat,'map',null,{moveTargetId});
  },MAP_POINT_CLICK_DEBOUNCE_MS);
}
function defaultMapCursor(){return (movePointId||addingPoints)?'crosshair':'';}
function restoreMapCursor(){try{map.getCanvas().style.cursor=defaultMapCursor();}catch(_){}}
function interactionStatusText(){
  if(addingPoints)return pointInputMode==='multi'?'Tambah titik aktif · Multi Titik. Klik peta untuk menambahkan outlet berikutnya.':'Tambah titik aktif · Satu Titik. Klik peta untuk memilih atau mengganti outlet.';
  return `Mode ${pointInputMode==='multi'?'Multi Titik':'Satu Titik'}. Tekan Mulai Tambah untuk memilih outlet.`;
}
function cancelMovePoint(){movePointId=null;restoreMapCursor();setStatus(interactionStatusText(),'neutral');}
function armMovePoint(id){if(!points.some(p=>p.point_id===id))return;closePointPopup();movePointId=id;setActivePoint(id,{openCard:true});try{map.getCanvas().style.cursor='crosshair';}catch(_){}setStatus(`Pindahkan ${pointName(id)}: klik lokasi baru pada peta. Tekan Esc untuk batal.`,'busy');showAppToast(`Klik lokasi baru untuk memindahkan ${pointName(id)}.`);}

function snapWarningThreshold(radius){return Math.max(150,Math.min(500,Number(radius||300)*0.65));}
function showAppToast(text,{duration=4200}={}){const toast=$('appToast');if(!toast)return;clearTimeout(appToastTimer);$('appToastText').textContent=text;toast.classList.remove('hidden');refreshIcons(toast);appToastTimer=setTimeout(()=>toast.classList.add('hidden'),duration);}
function showMultiModeHintOnce(){try{if(sessionStorage.getItem(MULTI_MODE_HINT_KEY)==='shown')return;sessionStorage.setItem(MULTI_MODE_HINT_KEY,'shown');}catch(_){}showAppToast('Mode Multi Titik dipilih. Tekan Mulai Tambah, lalu klik peta untuk menambahkan beberapa outlet.',{duration:5200});}
function isHeaderUiBlocked(){
  return Boolean(
    document.querySelector('.modal-backdrop:not(.hidden)') ||
    document.querySelector('.map-panel:not(.hidden)') ||
    document.querySelector('.dta-colorpicker-panel:not(.hidden)')
  );
}
function updateHeaderHandleInteractivity(){
  const blocked=isHeaderUiBlocked(),shell=$('headerHandleShell'),btn=$('headerHandle');
  shell?.classList.toggle('is-blocked',blocked);
  if(btn)btn.disabled=blocked;
  if(blocked&&$('appHeader')&&!$('appHeader').classList.contains('is-hidden'))setHeaderVisible(false);
}
function openMapModal(el){
  if(!el)return;
  try{modalCameraContext.set(el,getCameraState());}catch(_){}
  el.classList.remove('hidden');
  clearDtaHover();
  updateHeaderHandleInteractivity();
}
function closeMapModal(el){
  if(!el)return;
  el.classList.add('hidden');
  const c=modalCameraContext.get(el);
  if(c&&Array.isArray(c.center)){try{map.jumpTo({center:c.center,zoom:c.zoom,bearing:c.bearing,pitch:0});}catch(_){}}
  modalCameraContext.delete(el);
  updateHeaderHandleInteractivity();
}
function copyText(text,button=null){const done=()=>{if(button){const old=button.innerHTML;button.innerHTML='<i data-lucide="check"></i>';refreshIcons(button);setTimeout(()=>{button.innerHTML=old;refreshIcons(button);},1200);}};if(navigator.clipboard?.writeText){navigator.clipboard.writeText(text).then(done).catch(()=>{});}else{const t=document.createElement('textarea');t.value=text;document.body.appendChild(t);t.select();try{document.execCommand('copy');done();}catch(_){}t.remove();}}
function resultUiStatus(r,processing=false){if(processing)return {label:'Memproses',cls:'processing'};if(!r)return {label:'Menunggu',cls:'pending'};const pairs=r?.topology_qa?.pairs||[];const warning=pairs.some(x=>x?.status==='warning');if(warning)return {label:'Periksa batas',cls:'warning'};return null;}
function reindexPoints(){/* Internal IDs are stable; deleted slots may be reused by nextPointId(). */}

function dmsToDecimal(deg,min,sec,hem){
  let v=Math.abs(Number(deg))+(Number(min||0)/60)+(Number(sec||0)/3600);
  if(['S','W'].includes(String(hem).toUpperCase()))v=-v;
  return v;
}
function parseCoordinate(text){
  const raw=String(text||'').trim();
  if(!raw)throw new Error('Masukkan koordinat.');
  const dd=raw.match(/^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$/);
  if(dd){
    const lat=Number(dd[1]),lon=Number(dd[2]);
    if(Math.abs(lat)>90||Math.abs(lon)>180)throw new Error('Koordinat berada di luar rentang yang valid.');
    return {lat,lon};
  }
  const dmsRe=/(\d+(?:\.\d+)?)\s*[°º]\s*(\d+(?:\.\d+)?)?\s*['′]?\s*(\d+(?:\.\d+)?)?\s*["″]?\s*([NSEW])/gi;
  const matches=[...raw.matchAll(dmsRe)];
  if(matches.length>=2){
    let lat=null,lon=null;
    for(const m of matches){
      const v=dmsToDecimal(m[1],m[2],m[3],m[4]);
      const h=m[4].toUpperCase();
      if(h==='N'||h==='S')lat=v;
      if(h==='E'||h==='W')lon=v;
    }
    if(lat!==null&&lon!==null)return {lat,lon};
  }
  throw new Error('Format koordinat belum dikenali. Gunakan DD atau DMS seperti contoh.');
}

const BASEMAP_DEFS = {
  'world-topo':{tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}'],attribution:'Tiles © Esri',maxzoom:19},
  'esri-satellite':{tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],attribution:'Tiles © Esri',maxzoom:19},
  'osm':{tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],attribution:'© OpenStreetMap contributors',maxzoom:19},
  'google-maps':{tiles:['https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}'],attribution:'© Google',maxzoom:20},
  'google-satellite':{tiles:['https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}'],attribution:'© Google',maxzoom:20},
  'rbi':{tiles:['https://geoservices.big.go.id/rbi/rest/services/BASEMAP/Rupabumi_Indonesia/MapServer/tile/{z}/{y}/{x}'],attribution:'© Badan Informasi Geospasial',maxzoom:23},
  'esri-dark-gray':{tiles:['https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'],attribution:'Dark Gray Canvas © Esri',maxzoom:16},
  'esri-light-gray':{tiles:['https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}'],attribution:'Light Gray Canvas © Esri',maxzoom:16},
  'opentopomap':{tiles:['https://a.tile.opentopomap.org/{z}/{x}/{y}.png'],attribution:'© OpenStreetMap contributors, SRTM | © OpenTopoMap',maxzoom:17}
};
const BASEMAP_KEYS=Object.keys(BASEMAP_DEFS);
if(selectedLightBasemap!=='no-basemap'&&!BASEMAP_DEFS[selectedLightBasemap])selectedLightBasemap=DEFAULT_BASEMAP;
if(currentBasemap!=='no-basemap'&&!BASEMAP_DEFS[currentBasemap])currentBasemap=DEFAULT_BASEMAP;
function buildMapStyle(){
  const dark=document.documentElement.getAttribute('data-theme')==='dark';
  const sources={},layers=[{id:'basemap-background',type:'background',paint:{'background-color':dark?'#151d2b':'#eef1f4'}}];
  for(const [key,d] of Object.entries(BASEMAP_DEFS)){
    sources[`basemap-source-${key}`]={type:'raster',tiles:d.tiles,tileSize:256,maxzoom:d.maxzoom,attribution:d.attribution};
    layers.push({id:`basemap-layer-${key}`,type:'raster',source:`basemap-source-${key}`,layout:{visibility:key===currentBasemap?'visible':'none'},paint:{'raster-fade-duration':120}});
  }
  return {version:8,sources,layers};
}
function applyBasemapVisibility(){
  for(const key of BASEMAP_KEYS)setLayerVisibility(`basemap-layer-${key}`,key===currentBasemap);
  if(map.getLayer('basemap-background'))map.setPaintProperty('basemap-background','background-color',document.documentElement.getAttribute('data-theme')==='dark'?'#151d2b':'#eef1f4');
  updateBasemapGallery();
}

function updateBasemapGallery(){
  document.querySelectorAll('.basemap-card').forEach(card=>{
    const active=card.dataset.basemap===currentBasemap;
    card.classList.toggle('active',active);
    card.setAttribute('aria-pressed',active?'true':'false');
  });
  const noneBtn=$('noBasemapBtn');if(noneBtn){const active=currentBasemap==='no-basemap';noneBtn.classList.toggle('active',active);noneBtn.setAttribute('aria-pressed',active?'true':'false');}
}


class ExistingControl{
  constructor(id){this.id=id;this.el=null;}
  onAdd(){this.el=$(this.id);this.el.classList.remove('hidden');return this.el;}
  onRemove(){if(this.el?.parentNode)this.el.parentNode.removeChild(this.el);}
}

const savedCamera=restoredState.camera||{};
const map=new maplibregl.Map({
  container:'map',center:Array.isArray(savedCamera.center)?savedCamera.center:[110.1,-7.55],zoom:Number.isFinite(savedCamera.zoom)?savedCamera.zoom:7,bearing:Number.isFinite(savedCamera.bearing)?savedCamera.bearing:0,pitch:0,minPitch:0,maxPitch:0,pitchWithRotate:false,touchPitch:false,style:buildMapStyle(),
  locale:{'NavigationControl.ZoomIn':'Perbesar','NavigationControl.ZoomOut':'Perkecil','NavigationControl.ResetBearing':'Atur ulang arah','FullscreenControl.Enter':'Layar penuh','FullscreenControl.Exit':'Keluar layar penuh'}
});
map.addControl(new ExistingControl('mapSearchForm'),'top-left');
map.addControl(new ExistingControl('mapToolbarControl'),'bottom-right');
map.addControl(new ExistingControl('coordReadout'),'bottom-left');
map.addControl(new maplibregl.ScaleControl({maxWidth:140,unit:'metric'}),'bottom-left');

function makeHatchImage(color){
  const c=document.createElement('canvas');c.width=12;c.height=12;const x=c.getContext('2d');x.clearRect(0,0,12,12);x.strokeStyle=color;x.lineWidth=1.4;
  x.beginPath();x.moveTo(-3,3);x.lineTo(3,-3);x.moveTo(0,12);x.lineTo(12,0);x.moveTo(9,15);x.lineTo(15,9);x.stroke();return x.getImageData(0,0,12,12);
}
function ensureHatchImages(){
  for(let i=1;i<=MAX_POINTS;i++){
    const id=`O${i}`,key=`hatch-${id}`,data=makeHatchImage(POINT_COLORS[id]);
    if(map.hasImage(key))map.updateImage(key,data);else map.addImage(key,data,{pixelRatio:1});
  }
}
function riverDisplayAssetKeyForZoom(zoom=map?.getZoom?.()??0){
  // Manual order mode intentionally uses the full asset, because users may enable
  // any order at any zoom. Auto mode uses progressively more detailed files.
  if($('autoRiverZoom')?.checked===false)return 'official-rivers';
  if(zoom>=RIVER_FULL_DETAIL_ZOOM)return 'official-rivers';
  if(zoom>=12.5)return 'official-rivers-z12-14';
  if(zoom>=11.5)return 'official-rivers-z11-12';
  if(zoom>=10.5)return 'official-rivers-z10-11';
  if(zoom>=8.5)return 'official-rivers-z8-10';
  return 'official-rivers-z6-8';
}
function mapAssetUrl(key){
  const filename=MAP_ASSET_FILES[key];
  if(MAP_ASSETS_BASE&&filename){
    const suffix=MAP_ASSETS_VERSION?`?v=${encodeURIComponent(MAP_ASSETS_VERSION)}`:'';
    return `${MAP_ASSETS_BASE}/${filename}${suffix}`;
  }
  return `/api/map-assets/${key}`;
}
function riverDisplayAssetUrl(key=riverDisplayAssetKeyForZoom()){return mapAssetUrl(key);}
function updateRiverDisplaySource({force=false}={}){
  const source=map?.getSource?.('official-rivers');
  if(!source)return;
  const key=riverDisplayAssetKeyForZoom();
  if(!force&&key===currentRiverAssetKey)return;
  currentRiverAssetKey=key;
  riverLabelData=null;
  riverLabelDataKey=null;
  lastRiverLabelFilterSignature='';
  try{source.setData(riverDisplayAssetUrl(key));}catch(_){}
  updateRiverLabelFilter({force:true});
  if(batchResult?.results?.length)updateLabelDeclutter();
}

function riverOrderExpression(){
  // Runtime GeoJSON uses `river_order`; keep `river_order_int` as a backwards-compatible fallback.
  return ['to-number',['coalesce',['get','river_order_int'],['get','river_order']],0];
}
function riverFilter(k){
  const order=riverOrderExpression();
  // `other` is the display class for minor rivers beyond the mapped 1-3 hierarchy.
  // It intentionally also catches null/undefined order values from the source dataset.
  return k==='other'
    ? ['all',['!=',order,1],['!=',order,2],['!=',order,3]]
    : ['==',order,Number(k)];
}
function riverMapLabelExpression(){
  // `river_name` in official_rivers is the normalized base name (e.g. "Serayu").
  // Build the cartographic label here so stale/legacy `river_label` values cannot
  // accidentally remove the required compact prefix.
  return ['case',
    ['!=',['coalesce',['get','river_name'],''],''],
    ['concat','K. ',['to-string',['get','river_name']]],
    ['coalesce',['get','river_label'],'']
  ];
}
function riverLabelSizeExpression(){
  const order=riverOrderExpression();
  const sizeAt=(z)=>['match',order,1,z===7?11:14,2,z===7?10:12.5,3,z===7?9:11.5,z===7?8.5:10];
  return ['interpolate',['linear'],['zoom'],7,sizeAt(7),15,sizeAt(15)];
}
function riverLabelSortKeyExpression(){
  // Lower sort keys are placed first when overlap is disabled.
  // This gives the cartographic hierarchy: Orde 1 > Orde 2 > Orde 3 > others.
  return ['match',riverOrderExpression(),1,10,2,20,3,30,40];
}
function enabledRiverOrdersForCurrentZoom(){
  const auto=$('autoRiverZoom')?.checked!==false;
  const zoom=map?.getZoom?.() ?? 0;
  return RIVER_KEYS.filter(k=>{
    const enabled=document.querySelector(`.river-order-toggle[data-order="${k}"]`)?.checked!==false;
    return enabled && (!auto || zoom>=RIVER_ZOOM[k]);
  });
}
function riverLabelFilter(){
  const allowed=enabledRiverOrdersForCurrentZoom();
  if(!allowed.length)return ['==',1,0];
  const orderFilters=allowed.map(riverFilter);
  const hierarchy=orderFilters.length===1?orderFilters[0]:['any',...orderFilters];
  if(!hiddenRiverLabelIds.length)return hierarchy;
  const exclude=['!', ['in',['get','official_id'],['literal',hiddenRiverLabelIds]]];
  return ['all',hierarchy,exclude];
}
function updateRiverLabelFilter({force=false}={}){
  if(!map?.getLayer?.('official-river-labels'))return;
  const allowed=enabledRiverOrdersForCurrentZoom();
  const signature=`${allowed.join(',')}|${hiddenRiverLabelIds.join(',')}`;
  if(!force && signature===lastRiverLabelFilterSignature)return;
  lastRiverLabelFilterSignature=signature;
  map.setFilter('official-river-labels',riverLabelFilter());
}
function lineBase(){return Number($('lineWidth')?.value||2);}
function riverWidth(k){const b=lineBase(),m={1:1,2:.70,3:.48,other:.34}[k];return Math.max(.55,b*m);}

function addOperationalLayers(){
  const darkMap=document.documentElement.getAttribute('data-theme')==='dark';
  const labelHalo=darkMap?'rgba(10,17,29,.92)':'rgba(255,255,255,.97)';
  if(!map.getSource('esri-hillshade'))map.addSource('esri-hillshade',{type:'raster',tiles:['https://services.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}'],tileSize:256,maxzoom:16,attribution:'Hillshade © Esri'});
  if(!map.getLayer('esri-hillshade-layer'))map.addLayer({id:'esri-hillshade-layer',type:'raster',source:'esri-hillshade',layout:{visibility:$('showHillshade')?.checked?'visible':'none'},paint:{'raster-opacity':Number($('hillshadeOpacity')?.value||100)/100,'raster-fade-duration':0}});

  if(!map.getSource('official-basins'))map.addSource('official-basins',{type:'geojson',data:mapAssetUrl('official-basins'),tolerance:0,maxzoom:24,buffer:128});
  if(!map.getSource('official-basin-labels'))map.addSource('official-basin-labels',{type:'geojson',data:'/api/basin-labels'});
  if(!map.getLayer('official-basins-fill'))map.addLayer({id:'official-basins-fill',type:'fill',source:'official-basins',paint:{'fill-color':$('basinColor')?.value||'#9b7300','fill-opacity':0}});
  if(!map.getLayer('official-basins-line'))map.addLayer({id:'official-basins-line',type:'line',source:'official-basins',layout:{'line-join':'round','line-cap':'round'},paint:{'line-color':$('basinColor')?.value||'#9b7300','line-width':lineBase(),'line-opacity':1}});

  ensureHatchImages();
  for(let i=1;i<=MAX_POINTS;i++){
    const id=`O${i}`;
    if(!map.getSource(`dta-${id}`))map.addSource(`dta-${id}`,{type:'geojson',data:emptyFC(),tolerance:0,maxzoom:24});
    if(!map.getSource(`dta-incremental-${id}`))map.addSource(`dta-incremental-${id}`,{type:'geojson',data:emptyFC(),tolerance:0,maxzoom:24});
    if(!map.getLayer(`dta-${id}-hatch`))map.addLayer({id:`dta-${id}-hatch`,type:'fill',source:`dta-incremental-${id}`,layout:{visibility:$('showHatch')?.checked?'visible':'none'},paint:{'fill-pattern':`hatch-${id}`,'fill-opacity':Number($('hatchOpacity')?.value||22)/100}});
    if(!map.getLayer(`dta-${id}-hit`))map.addLayer({id:`dta-${id}-hit`,type:'fill',source:`dta-incremental-${id}`,paint:{'fill-color':'#000000','fill-opacity':0.001}});
    if(!map.getLayer(`dta-${id}-hover`))map.addLayer({id:`dta-${id}-hover`,type:'line',source:`dta-${id}`,layout:{'line-join':'round','line-cap':'round'},paint:{'line-color':POINT_COLORS[id],'line-width':0,'line-opacity':0}});
    if(!map.getLayer(`dta-${id}-line`))map.addLayer({id:`dta-${id}-line`,type:'line',source:`dta-${id}`,layout:{'line-join':'round','line-cap':'round'},paint:{'line-color':POINT_COLORS[id],'line-width':lineBase(),'line-opacity':1}});
  }

  if(!map.getSource('official-rivers')){currentRiverAssetKey=riverDisplayAssetKeyForZoom();map.addSource('official-rivers',{type:'geojson',data:riverDisplayAssetUrl(currentRiverAssetKey),tolerance:0,maxzoom:24,buffer:128,lineMetrics:true});}
  // Draw every river line first. Labels are intentionally kept in ONE symbol layer below,
  // so symbol-sort-key can enforce collision priority across the complete river hierarchy.
  for(const k of RIVER_KEYS){
    if(!map.getLayer(`official-river-${k}`))map.addLayer({id:`official-river-${k}`,type:'line',source:'official-rivers',filter:riverFilter(k),minzoom:RIVER_ZOOM[k],layout:{'line-join':'round','line-cap':'round'},paint:{'line-color':$('riverColor')?.value||'#0083d7','line-width':riverWidth(k),'line-opacity':1}});
  }
  if(!map.getLayer('official-river-labels'))map.addLayer({
    id:'official-river-labels',type:'symbol',source:'official-rivers',filter:riverLabelFilter(),minzoom:RIVER_ZOOM[1],
    layout:{
      'symbol-placement':'line','symbol-spacing':220,'symbol-sort-key':riverLabelSortKeyExpression(),'symbol-z-order':'source',
      // Custom river labels come from official-rivers assets generated from the /data or R2 river network.
      // Keep the default MapLibre sans-serif text stack here; this does not affect raster basemap labels.
      'text-field':riverMapLabelExpression(),'text-size':riverLabelSizeExpression(),
      'text-rotation-alignment':'map','text-pitch-alignment':'map','text-keep-upright':true,'text-max-angle':70,
      'text-offset':[0,-.55],'text-padding':1,'text-allow-overlap':false,'text-ignore-placement':false
    },
    paint:{'text-color':$('riverColor')?.value||'#0083d7','text-halo-color':labelHalo,'text-halo-width':1.45}
  });
  if(!map.getLayer('official-basin-label'))map.addLayer({id:'official-basin-label',type:'symbol',source:'official-basin-labels',minzoom:5.5,layout:{'text-field':['concat','DAS ',['get','basin_name']],'text-size':['interpolate',['linear'],['zoom'],5.5,16,9,13,12,10,15,9],'text-letter-spacing':.04,'text-allow-overlap':false,'text-ignore-placement':false},paint:{'text-color':$('basinColor')?.value||'#9b7300','text-halo-color':labelHalo,'text-halo-width':1.6,'text-opacity':['interpolate',['linear'],['zoom'],5.5,1,12,.78,15,.55]}});

  if(!map.getSource('requested-points'))map.addSource('requested-points',{type:'geojson',data:emptyFC()});
    if(!map.getLayer('requested-points'))map.addLayer({id:'requested-points',type:'circle',source:'requested-points',paint:{'circle-radius':5.5,'circle-color':['get','color'],'circle-stroke-color':'#fff','circle-stroke-width':1.8}});
  if(!map.getLayer('requested-point-labels'))map.addLayer({id:'requested-point-labels',type:'symbol',source:'requested-points',layout:{'text-field':['get','display_name'],'text-size':12,'text-offset':[0,1.25],'text-anchor':'top','text-allow-overlap':false},paint:{'text-color':'#17233b','text-halo-color':'#fff','text-halo-width':1.4}});

  if(!map.getSource('location-preview'))map.addSource('location-preview',{type:'geojson',data:emptyFC()});
  if(!map.getLayer('location-preview-halo'))map.addLayer({id:'location-preview-halo',type:'circle',source:'location-preview',paint:{'circle-radius':10,'circle-color':'rgba(255,255,255,.78)','circle-stroke-color':'#223468','circle-stroke-width':1.5}});
  if(!map.getLayer('location-preview-point'))map.addLayer({id:'location-preview-point',type:'circle',source:'location-preview',paint:{'circle-radius':4.5,'circle-color':'#223468','circle-stroke-color':'#ffffff','circle-stroke-width':1.3}});

  if(!map.getSource('snap-preview'))map.addSource('snap-preview',{type:'geojson',data:emptyFC()});
  if(!map.getLayer('snap-preview-line'))map.addLayer({id:'snap-preview-line',type:'line',source:'snap-preview',filter:['==',['get','kind'],'connector'],paint:{'line-color':'#596779','line-width':1.6,'line-dasharray':[2,2],'line-opacity':.9}});
  if(!map.getLayer('snap-preview-requested'))map.addLayer({id:'snap-preview-requested',type:'circle',source:'snap-preview',filter:['==',['get','kind'],'requested'],paint:{'circle-radius':6,'circle-color':'#fff','circle-stroke-color':'#596779','circle-stroke-width':2}});
  if(!map.getLayer('snap-preview-snapped'))map.addLayer({id:'snap-preview-snapped',type:'circle',source:'snap-preview',filter:['==',['get','kind'],'snapped'],paint:{'circle-radius':7,'circle-color':'#223468','circle-stroke-color':'#fff','circle-stroke-width':2.2}});

  if(!map.getSource('measure-line'))map.addSource('measure-line',{type:'geojson',data:emptyFC()});
  if(!map.getLayer('measure-line'))map.addLayer({id:'measure-line',type:'line',source:'measure-line',paint:{'line-color':'#223468','line-width':2,'line-dasharray':[2,1.5]}});
  if(!map.getSource('measure-points'))map.addSource('measure-points',{type:'geojson',data:emptyFC()});
  if(!map.getLayer('measure-points'))map.addLayer({id:'measure-points',type:'circle',source:'measure-points',paint:{'circle-radius':4,'circle-color':'#fff','circle-stroke-color':'#223468','circle-stroke-width':2}});

  renderRequestedPoints();
  renderDtaLayers();
  applyLayerState();
  updateLineWidths();
  updateRiverVisibility();
  refreshIcons();
}

function applyLayerState(){
  setLayerVisibility('esri-hillshade-layer',$('showHillshade').checked);
  setLayerVisibility('official-basins-fill',$('showBasins').checked);
  setLayerVisibility('official-basins-line',$('showBasins').checked);
  setLayerVisibility('official-basin-label',$('showBasins').checked&&$('showBasinLabels').checked);
  for(let i=1;i<=MAX_POINTS;i++)setLayerVisibility(`dta-O${i}-hatch`,$('showHatch').checked);
  updateRiverVisibility();
}
function updateRiverVisibility(){
  const show=$('showRivers').checked,showLabels=$('showRiverLabels').checked,auto=$('autoRiverZoom').checked;
  for(const k of RIVER_KEYS){
    const enabled=document.querySelector(`.river-order-toggle[data-order="${k}"]`)?.checked!==false;
    const line=`official-river-${k}`;
    if(map.getLayer(line)){map.setLayerZoomRange(line,auto?RIVER_ZOOM[k]:0,24);setLayerVisibility(line,show&&enabled);}
  }
  if(map.getLayer('official-river-labels')){
    map.setLayerZoomRange('official-river-labels',auto?RIVER_ZOOM[1]:0,24);
    setLayerVisibility('official-river-labels',show&&showLabels);
    updateRiverLabelFilter({force:true});
  }
}
function updateLineWidths(){
  const b=lineBase();$('lineWidthValue').textContent=`${b.toFixed(1)} px`;
  if(map.getLayer('official-basins-line'))map.setPaintProperty('official-basins-line','line-width',b);
  for(let i=1;i<=MAX_POINTS;i++)if(map.getLayer(`dta-O${i}-line`))map.setPaintProperty(`dta-O${i}-line`,'line-width',b);
  for(const k of RIVER_KEYS)if(map.getLayer(`official-river-${k}`))map.setPaintProperty(`official-river-${k}`,'line-width',riverWidth(k));
  applyDtaHighlight();
}
function updateHatchOpacity(){const v=Number($('hatchOpacity').value)/100;$('hatchOpacityValue').textContent=`${$('hatchOpacity').value}%`;for(let i=1;i<=MAX_POINTS;i++)if(map.getLayer(`dta-O${i}-hatch`))map.setPaintProperty(`dta-O${i}-hatch`,'fill-opacity',v);}
function raiseDtaHoverBelowOutlet(id){
  const layer=`dta-${id}-hover`;
  if(!map.getLayer(layer))return;
  try{
    if(map.getLayer('requested-points'))map.moveLayer(layer,'requested-points');
    else map.moveLayer(layer);
  }catch(_){}
}
function applyDtaHighlight(){
  const selected=activePointId;const hovered=hoverEmphasisId;const hoverKind=hoverEmphasisKind;const b=lineBase();
  for(let i=1;i<=MAX_POINTS;i++){
    const id=`O${i}`;
    if(map.getLayer(`dta-${id}-line`)){
      const active=id===selected;
      map.setPaintProperty(`dta-${id}-line`,'line-width',active?Math.max(b*1.7,b+1.1):b);
      map.setPaintProperty(`dta-${id}-line`,'line-opacity',selected&&!active ? .62 : 1);
    }
    if(map.getLayer(`dta-${id}-hover`)){
      const hoverOnDta=id===hovered&&hoverKind==='dta';
      map.setPaintProperty(`dta-${id}-hover`,'line-color',POINT_COLORS[id]);
      map.setPaintProperty(`dta-${id}-hover`,'line-width',hoverOnDta?Math.max(b*2.35,b+2):0);
      map.setPaintProperty(`dta-${id}-hover`,'line-opacity',hoverOnDta?.95:0);
    }
  }
  if(map.getLayer('requested-points')){
    map.setPaintProperty('requested-points','circle-radius',['case',['==',['get','point_id'],hovered||'__none__'],8.2,['==',['get','point_id'],selected||'__none__'],7.2,5.5]);
    map.setPaintProperty('requested-points','circle-stroke-width',['case',['==',['get','point_id'],hovered||'__none__'],2.8,['==',['get','point_id'],selected||'__none__'],2.4,1.8]);
  }
}
function setActivePoint(id,{openCard=true}={}){activePointId=id||null;if(openCard&&id){const card=pointListEl.querySelector(`.point-card[data-point-id="${id}"]`);if(card){card.open=true;pointListEl.querySelectorAll('.point-card').forEach(other=>{if(other!==card)other.open=false;});}}applyDtaHighlight();schedulePersistState();}
let activeDtaColorPointId=null;
let dtaColorPickerReady=false;
let dtaColorSyncing=false;

function closeDtaColorPicker(){
  const panel=$('dtaColorPickerPanel');
  if(panel){
    panel.classList.add('hidden');
    panel.classList.remove('native-picker-proxy');
    panel.style.removeProperty('--native-picker-left');
    panel.style.removeProperty('--native-picker-top');
  }
  activeDtaColorPointId=null;
  updateHeaderHandleInteractivity();
}

function positionDtaColorPicker(anchor){
  const panel=$('dtaColorPickerPanel');if(!panel||!anchor)return;
  panel.classList.remove('hidden');
  panel.style.visibility='hidden';
  const r=anchor.getBoundingClientRect(),pw=panel.offsetWidth||286,ph=panel.offsetHeight||330,m=10;
  let left=Math.min(Math.max(m,r.left),window.innerWidth-pw-m);
  let top=r.bottom+7;
  if(top+ph>window.innerHeight-m)top=Math.max(m,r.top-ph-7);
  panel.style.left=`${Math.round(left)}px`;
  panel.style.top=`${Math.round(top)}px`;
  panel.style.visibility='';
}

function normalizeHexColor(value){
  let text=String(value??'').trim();
  if(!text)return null;
  if(!text.startsWith('#'))text=`#${text}`;
  return /^#[0-9a-f]{6}$/i.test(text)?text.toLowerCase():null;
}
function hexToRgb(hex){
  const color=normalizeHexColor(hex);if(!color)return null;
  const n=parseInt(color.slice(1),16);
  return {r:(n>>16)&255,g:(n>>8)&255,b:n&255};
}
function rgbToHex(r,g,b){
  const clean=[r,g,b].map(v=>Math.max(0,Math.min(255,Math.round(Number(v)||0))));
  return `#${clean.map(v=>v.toString(16).padStart(2,'0')).join('')}`;
}
function syncDtaColorInputs(color){
  const hex=normalizeHexColor(color);if(!hex)return;
  dtaColorSyncing=true;
  const nativeInput=$('dtaColorNativeInput'),hexInput=$('dtaColorHexInput'),msg=$('dtaColorInputMessage');
  if(nativeInput){nativeInput.value=hex;nativeInput.classList.remove('is-invalid');}
  if(hexInput){hexInput.value=hex;hexInput.classList.remove('is-invalid');}
  if(msg){msg.textContent='Gunakan pemilih warna atau masukkan HEX #RRGGBB.';msg.classList.remove('error');}
  dtaColorSyncing=false;
}
function renderDtaColorPalette(){ }
function applyDtaCustomHex(){
  if(dtaColorSyncing||!activeDtaColorPointId)return;
  const input=$('dtaColorHexInput'),msg=$('dtaColorInputMessage');
  const color=normalizeHexColor(input?.value);
  if(!color){
    input?.classList.add('is-invalid');
    if(msg){msg.textContent='HEX harus menggunakan format #RRGGBB.';msg.classList.add('error');}
    return;
  }
  input.classList.remove('is-invalid');
  setDtaColor(activeDtaColorPointId,color);
  syncDtaColorInputs(color);
}
function applyDtaNativeColor(){
  if(dtaColorSyncing||!activeDtaColorPointId)return;
  const input=$('dtaColorNativeInput');
  const color=normalizeHexColor(input?.value);
  if(!color)return;
  setDtaColor(activeDtaColorPointId,color);
  syncDtaColorInputs(color);
}
function finishDtaNativeColorPicker(){
  const panel=$('dtaColorPickerPanel');
  setTimeout(()=>{
    panel?.classList.remove('native-picker-proxy');
    panel?.style.removeProperty('--native-picker-left');
    panel?.style.removeProperty('--native-picker-top');
  },80);
}
function ensureDtaColorPicker(){
  if(dtaColorPickerReady)return true;
  const panel=$('dtaColorPickerPanel');
  if(!panel||!$('dtaColorNativeInput')||!$('dtaColorHexInput'))return false;
  $('dtaColorNativeInput').addEventListener('input',applyDtaNativeColor);
  $('dtaColorNativeInput').addEventListener('change',()=>{applyDtaNativeColor();finishDtaNativeColorPicker();});
  $('dtaColorHexInput').addEventListener('change',applyDtaCustomHex);
  $('dtaColorHexInput').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();applyDtaCustomHex();}});
  dtaColorPickerReady=true;
  return true;
}
function openDtaColorPicker(id,anchor){
  if(!points.some(p=>p.point_id===id))return;
  activeDtaColorPointId=id;
  if(!ensureDtaColorPicker()){
    showAppToast('Pemilih warna belum tersedia.');
    return;
  }

  const panel=$('dtaColorPickerPanel'),input=$('dtaColorNativeInput');
  const color=normalizeHexColor(POINT_COLORS[id])||POINT_PALETTE[0];
  syncDtaColorInputs(color);

  // Browser/OS positions the native picker relative to the color input.
  // Move the transparent proxy directly onto the clicked Warna button first.
  if(panel&&anchor){
    const r=anchor.getBoundingClientRect();
    const x=Math.max(4,Math.min(window.innerWidth-8,r.left+(r.width/2)));
    const y=Math.max(4,Math.min(window.innerHeight-8,r.top+(r.height/2)));
    panel.style.setProperty('--native-picker-left',`${Math.round(x)}px`);
    panel.style.setProperty('--native-picker-top',`${Math.round(y)}px`);
  }
  panel?.classList.add('native-picker-proxy');

  try{
    if(typeof input.showPicker==='function')input.showPicker();
    else input.click();
  }catch(_){
    try{input.click();}catch(__){}
  }
  // Proxy remains renderable until the native picker fires change.
}
function setDtaColor(id,color,{save=true}={}){
  const normalized=normalizeHexColor(color);if(!normalized)return;
  POINT_COLORS[id]=normalized;
  if(map.getLayer(`dta-${id}-line`))map.setPaintProperty(`dta-${id}-line`,'line-color',normalized);
  if(map.getLayer(`dta-${id}-hover`))map.setPaintProperty(`dta-${id}-hover`,'line-color',normalized);
  if(map.hasImage(`hatch-${id}`))map.updateImage(`hatch-${id}`,makeHatchImage(normalized));
  const card=pointListEl.querySelector(`.point-card[data-point-id="${id}"]`);
  if(card){
    card.style.setProperty('--point-color',normalized);
    const chip=card.querySelector('.point-name-chip');
    if(chip){chip.style.background=normalized;chip.style.color=readableTextColor(normalized);}
  }
  const popup=pointPopup?.getElement?.()?.querySelector(`.existing-point-menu[data-point-id="${id}"]`);
  const popupChip=popup?.querySelector('.existing-point-name-chip');
  if(popupChip){popupChip.style.background=normalized;popupChip.style.color=readableTextColor(normalized);}
  renderRequestedPoints();
  if(activeDtaColorPointId===id&&!dtaColorSyncing){
    syncDtaColorInputs(normalized);
    renderDtaColorPalette(id);
  }
  if(save)schedulePersistState();
}
function setBasemap(name,{userInitiated=true}={}){
  if(name!=='esri-dark-gray')selectedLightBasemap=name;
  currentBasemap=name;
  applyBasemapVisibility();
  persistState();
}
function applyMapTheme(theme){
  if(theme==='dark'){
    if(currentBasemap!=='esri-dark-gray'){
      selectedLightBasemap=currentBasemap;
      setBasemap('esri-dark-gray',{userInitiated:false});
    }else applyBasemapVisibility();
  }else if(currentBasemap==='esri-dark-gray'){
    setBasemap(selectedLightBasemap||DEFAULT_BASEMAP,{userInitiated:false});
  }else applyBasemapVisibility();
}


function renderRequestedPoints(){
  if(!map.getSource('requested-points'))return;
  const byId=new Map((batchResult?.results||[]).map(r=>[r.point_id,r]));
  map.getSource('requested-points').setData({type:'FeatureCollection',features:points.map(p=>{const r=byId.get(p.point_id);const lon=Number.isFinite(Number(r?.snapped_lon))?Number(r.snapped_lon):p.lon;const lat=Number.isFinite(Number(r?.snapped_lat))?Number(r.snapped_lat):p.lat;return {type:'Feature',properties:{point_id:p.point_id,color:POINT_COLORS[p.point_id],display_name:p.label?.trim()||p.point_id},geometry:{type:'Point',coordinates:[lon,lat]}};})});
  applyDtaHighlight();
}
function clearSnapPreview(){previewSnapState=null;map.getSource('snap-preview')?.setData(emptyFC());}
function renderSnapPreview(requested,snapped){
  if(!map.getSource('snap-preview'))return;
  const features=[{type:'Feature',properties:{kind:'requested'},geometry:{type:'Point',coordinates:[requested.lon,requested.lat]}}];
  if(snapped&&Number.isFinite(snapped.lon)&&Number.isFinite(snapped.lat)){
    features.push({type:'Feature',properties:{kind:'snapped'},geometry:{type:'Point',coordinates:[snapped.lon,snapped.lat]}});
    if(haversineMeters(requested.lon,requested.lat,snapped.lon,snapped.lat)>.25)features.push({type:'Feature',properties:{kind:'connector'},geometry:{type:'LineString',coordinates:[[requested.lon,requested.lat],[snapped.lon,snapped.lat]]}});
  }
  previewSnapState={requested,snapped};map.getSource('snap-preview').setData({type:'FeatureCollection',features});
}
function clearDtaSources(){for(let i=1;i<=MAX_POINTS;i++){const id=`O${i}`;map.getSource(`dta-${id}`)?.setData(emptyFC());map.getSource(`dta-incremental-${id}`)?.setData(emptyFC());}}
function renderDtaLayers(){
  if(!map.getSource('dta-O1'))return;
  clearDtaSources();
  if(!batchResult?.results){updateLabelDeclutter();return;}
  for(const r of batchResult.results){
    map.getSource(`dta-${r.point_id}`)?.setData({type:'Feature',properties:{point_id:r.point_id},geometry:r.dta_geojson});
    map.getSource(`dta-incremental-${r.point_id}`)?.setData({type:'Feature',properties:{point_id:r.point_id},geometry:r.dta_incremental_geojson||r.dta_geojson});
  }
  updateLabelDeclutter();applyDtaHighlight();
}
function pointInRing(point,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const xi=ring[i][0],yi=ring[i][1],xj=ring[j][0],yj=ring[j][1];const intersect=((yi>point[1])!==(yj>point[1]))&&(point[0]<(xj-xi)*(point[1]-yi)/(yj-yi||1e-15)+xi);if(intersect)inside=!inside;}return inside;}
function pointInGeometry(point,g){if(!g)return false;const inPoly=poly=>{if(!poly?.length||!pointInRing(point,poly[0]))return false;for(let i=1;i<poly.length;i++)if(pointInRing(point,poly[i]))return false;return true;};if(g.type==='Polygon')return inPoly(g.coordinates);if(g.type==='MultiPolygon')return g.coordinates.some(inPoly);return false;}
async function ensureBasinLabelData(){if(basinLabelData)return basinLabelData;try{basinLabelData=await fetch('/api/basin-labels').then(r=>r.json());}catch(_){basinLabelData=null;}return basinLabelData;}
async function ensureRiverLabelData(){const key=riverDisplayAssetKeyForZoom();if(riverLabelData&&riverLabelDataKey===key)return riverLabelData;try{riverLabelData=await fetch(riverDisplayAssetUrl(key)).then(r=>r.ok?r.json():null);riverLabelDataKey=riverLabelData?key:null;}catch(_){riverLabelData=null;riverLabelDataKey=null;}return riverLabelData;}
function approximateLineMidpoint(geometry){
  if(!geometry)return null;
  const lines=geometry.type==='LineString'?[geometry.coordinates]:(geometry.type==='MultiLineString'?geometry.coordinates:[]);
  let best=null,bestLength=-1;
  for(const line of lines){if(!line?.length)continue;let length=0;for(let i=1;i<line.length;i++){const dx=line[i][0]-line[i-1][0],dy=line[i][1]-line[i-1][1];length+=Math.hypot(dx,dy);}if(length>bestLength){bestLength=length;best=line;}}
  if(!best?.length)return null;if(best.length===1)return best[0];
  const target=bestLength/2;let acc=0;
  for(let i=1;i<best.length;i++){const a=best[i-1],b=best[i],seg=Math.hypot(b[0]-a[0],b[1]-a[1]);if(acc+seg>=target){const t=seg?((target-acc)/seg):0;return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];}acc+=seg;}
  return best[Math.floor(best.length/2)];
}
async function updateLabelDeclutter(){
  const geoms=(batchResult?.results||[]).map(r=>r.dta_geojson).filter(Boolean);
  const basinSrc=map.getSource('official-basin-labels');
  if(basinSrc){
    const full=await ensureBasinLabelData();
    if(full?.features){const filtered=geoms.length?{type:'FeatureCollection',features:full.features.filter(f=>!geoms.some(g=>pointInGeometry(f.geometry.coordinates,g)))}:full;try{basinSrc.setData(filtered);}catch(_){}}
  }

  // River labels must remain visible above the DTA hatch. Do not remove labels
  // merely because their midpoint falls inside a delineated polygon; collision is
  // handled only by MapLibre's symbol placement / river-order priority.
  hiddenRiverLabelIds=[];
  if(map.getLayer('official-river-labels')){
    updateRiverLabelFilter({force:true});
    map.setLayoutProperty('official-river-labels','symbol-spacing',220);
  }
}
function cancelDtaHoverDelay(){
  clearTimeout(hoverDelayTimer);
  hoverDelayTimer=null;
  hoverCandidateId=null;
  hoverCandidateLngLat=null;
  hoverCandidateKind=null;
}
function setProgressiveMoving(on){
  progressiveMoving=on;if(on)clearDtaHover();if(!map?.getStyle?.())return;
  for(let i=1;i<=MAX_POINTS;i++){const id=`dta-O${i}-hatch`;if(map.getLayer(id))setLayerVisibility(id,on?false:Boolean($('showHatch')?.checked));}
}
function hoverPopupHtml(id,kind){
  const r=pointResult(id),color=POINT_COLORS[id]||POINT_PALETTE[0],name=pointName(id);
  const river=riverNameForUi(r?.official_river?.name),basin=r?.official_basin?.name||r?.requested_official_basin?.name||'—';
  const area=r?`${formatArea(r.area_km2)} km²`:'—';
  return `<div class="dta-hover-card point-hover-card"><span class="dta-hover-chip" style="background:${color};color:${readableTextColor(color)}">${escapeHtml(name)}</span><strong>${escapeHtml(area)}</strong><span>${escapeHtml(river)} · DAS ${escapeHtml(basin)}</span></div>`;
}
function showDtaHover(id,lngLat,kind='dta'){
  if(!id||!lngLat||isHeaderUiBlocked()||pointPopup||measureMode||progressiveMoving){clearDtaHover();return;}

  // In idle mode the DTA polygon behaves like its outlet: pointer + compact hover popup.
  // During an active add-point session the polygon becomes selectable map area, so no popup
  // competes with the crosshair interaction. Existing outlet markers always keep priority.
  if(kind==='dta'&&addingPoints){clearDtaHover();restoreMapCursor();return;}
  if(kind==='dta')raiseDtaHoverBelowOutlet(id);

  // Outlet and idle polygon hover use the same compact popup.
  if(hoverPointId===id&&hoverShownKind===kind&&dtaHoverPopup){
    try{dtaHoverPopup.setLngLat(lngLat);}catch(_){}
    hoverEmphasisId=id;
    hoverEmphasisKind=kind;
    applyDtaHighlight();
    return;
  }

  if(dtaHoverPopup){try{dtaHoverPopup.remove();}catch(_){}}
  dtaHoverPopup=new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:12,className:'dta-hover-popup'})
    .setLngLat(lngLat)
    .setHTML(hoverPopupHtml(id,kind))
    .addTo(map);

  hoverPointId=id;
  hoverShownKind=kind;
  hoverEmphasisId=id;
  hoverEmphasisKind=kind;
  applyDtaHighlight();
}
function clearDtaHover(){
  cancelDtaHoverDelay();
  hoverPointId=null;
  hoverShownKind=null;
  hoverEmphasisId=null;
  hoverEmphasisKind=null;
  if(dtaHoverPopup){try{dtaHoverPopup.remove();}catch(_){}dtaHoverPopup=null;}
  applyDtaHighlight();
  restoreMapCursor();
}
function queueDtaHover(id,lngLat,kind='dta'){
  if(!id||!lngLat){clearDtaHover();return;}
  if(hoverPointId===id&&hoverShownKind===kind&&dtaHoverPopup){showDtaHover(id,lngLat,kind);return;}
  if(hoverCandidateId===id&&hoverCandidateKind===kind)return;
  cancelDtaHoverDelay();
  hoverCandidateId=id;
  hoverCandidateKind=kind;
  hoverCandidateLngLat=lngLat;
  hoverDelayTimer=setTimeout(()=>{
    const cid=hoverCandidateId,ckind=hoverCandidateKind,clng=hoverCandidateLngLat;
    hoverDelayTimer=null;hoverCandidateId=null;hoverCandidateKind=null;hoverCandidateLngLat=null;
    showDtaHover(cid,clng,ckind);
  },140);
}
function clearResults(){batchResult=null;clearDtaSources();clearSnapPreview();window.clearHssResults?.();renderPointCards();renderRelationship(null);$('downloadBtn').disabled=true;if($('hssAnalysisBtn'))$('hssAnalysisBtn').disabled=true;if($('focusAllDtaBtn'))$('focusAllDtaBtn').disabled=true;updateLabelDeclutter();setStatus(interactionStatusText(),'neutral');}

async function reconcileCachedResults({guard=null}={}){
  if(!batchResult?.results?.length){if(!points.length)clearResults();return true;}
  const ownsOperation=typeof guard!=='function';
  const operationSerial=ownsOperation?++delineationOperationSerial:null;
  const operationIsCurrent=()=>ownsOperation?operationSerial===delineationOperationSerial:guard();
  const byId=new Map(batchResult.results.map(r=>[r.point_id,r]));
  const cached=points.map(p=>byId.get(p.point_id)).filter(Boolean);
  if(!cached.length){clearResults();return true;}
  if(delineationAbortController){try{delineationAbortController.abort();}catch(_){}delineationAbortController=null;}
  const reconcileRequestId=`${Date.now()}-reconcile-${++delineationRequestSerial}`;
  const response=await fetch('/api/reconcile-results',{method:'POST',headers:{'Content-Type':'application/json','X-DTA-Client-ID':DTA_CLIENT_ID,'X-DTA-Request-ID':reconcileRequestId},body:JSON.stringify({results:cached})});
  const payload=await response.json();
  if(!operationIsCurrent())return false;
  if(!response.ok)throw parseApiError(payload,'Pembaruan hubungan DTA gagal.');
  batchResult=payload;renderDtaLayers();renderRequestedPoints();renderPointCards();renderRelationship(payload.network_analysis);$('downloadBtn').disabled=false;if($('hssAnalysisBtn'))$('hssAnalysisBtn').disabled=false;if($('focusAllDtaBtn'))$('focusAllDtaBtn').disabled=false;persistState();
  return true;
}

async function runBatchDelineation({fit=true,onlyPointId=null}={}){
  if(!points.length){clearResults();return;}
  const target=onlyPointId?points.find(p=>p.point_id===onlyPointId):null;
  const requestPoints=(target?[target]:points).map(p=>({...p}));
  const requestSerial=++delineationRequestSerial;
  const operationSerial=++delineationOperationSerial;
  const requestSnapRadiusM=Number(snapRadiusEl.value);
  const requestBoundaryMatchM=Number(boundaryMatchEl.value);
  if(delineationAbortController){try{delineationAbortController.abort();}catch(_){}}
  const requestController=new AbortController();
  delineationAbortController=requestController;
  const requestId=`${Date.now()}-${requestSerial}`;
  if(target)latestDelineationSerialByPoint.set(target.point_id,requestSerial);
  const samePoint=(snapshot)=>{const current=points.find(p=>p.point_id===snapshot.point_id);return Boolean(current&&Number(current.lon)===Number(snapshot.lon)&&Number(current.lat)===Number(snapshot.lat));};
  const requestIsCurrent=()=>operationSerial===delineationOperationSerial&&(target
    ? latestDelineationSerialByPoint.get(target.point_id)===requestSerial&&samePoint(requestPoints[0])
    : requestPoints.length===points.length&&requestPoints.every(snapshot=>samePoint(snapshot)));
  processingPointIds=new Set(target?[target.point_id]:points.map(p=>p.point_id));renderPointCards();setStatus(target?`Menghitung DTA ${pointName(target.point_id)}…`:'Menghitung DTA…','busy');
  try{
    const response=await fetch('/api/delineate-multi',{
      method:'POST',
      headers:{'Content-Type':'application/json','X-DTA-Client-ID':DTA_CLIENT_ID,'X-DTA-Request-ID':requestId},
      signal:requestController.signal,
      body:JSON.stringify({points:requestPoints.map(({point_id,lon,lat,source,label})=>({point_id,lon,lat,source,label})),snap_radius_m:requestSnapRadiusM,boundary_match_m:requestBoundaryMatchM,paek_tolerance_m:150,vw_tolerance_m:4,decimal_separator:decimalSeparator})
    });
    const payload=await response.json();
    if(!requestIsCurrent())return null;
    if(!response.ok)throw parseApiError(payload,'Delineasi gagal.');
    if(target&&batchResult?.results?.length){
      const byId=new Map(batchResult.results.map(r=>[r.point_id,r]));byId.set(target.point_id,payload.results[0]);
      batchResult={results:points.map(p=>byId.get(p.point_id)).filter(Boolean),network_analysis:null};
      const reconciled=await reconcileCachedResults({guard:requestIsCurrent});
      if(!reconciled||!requestIsCurrent())return null;
    }else{
      if(!requestIsCurrent())return null;
      batchResult=payload;renderDtaLayers();renderRequestedPoints();renderRelationship(payload.network_analysis);$('downloadBtn').disabled=false;if($('hssAnalysisBtn'))$('hssAnalysisBtn').disabled=false;if($('focusAllDtaBtn'))$('focusAllDtaBtn').disabled=false;persistState();
    }
    if(!requestIsCurrent())return null;
    if(target)window.invalidateHssForPoint?.(target.point_id);else window.invalidateAllHss?.();
    setStatus(`${points.length} DTA berhasil dihitung.`,'success');clearSnapPreview();if(fit)fitToResults();
    return true;
  }catch(err){
    // A slow Vercel response from an older outlet must never roll back or overwrite a newer move.
    if(err?.name==='AbortError')return null;
    if(!requestIsCurrent())return null;
    if(err?.code==='request_superseded')return null;
    if(err?.code==='karst_detected'){showKarst(err);return false;}
    if(err?.code==='outside_region'){showOutside();return false;}
    setStatus(err?.message||String(err),'error');
    return false;
  }finally{
    if(delineationAbortController===requestController)delineationAbortController=null;
    if(target){
      if(latestDelineationSerialByPoint.get(target.point_id)===requestSerial){processingPointIds.delete(target.point_id);renderPointCards();}
    }else if(requestIsCurrent()){processingPointIds.clear();renderPointCards();}
  }
}

function fitToResults(){
  if(!batchResult?.results?.length)return;const b=new maplibregl.LngLatBounds();
  const extendGeom=g=>{if(!g)return;if(g.type==='Polygon')for(const ring of g.coordinates)for(const c of ring)b.extend(c);else if(g.type==='MultiPolygon')for(const p of g.coordinates)for(const ring of p)for(const c of ring)b.extend(c);};
  batchResult.results.forEach(r=>extendGeom(r.dta_geojson));
  if(!b.isEmpty())map.fitBounds(b,{padding:{top:80,bottom:70,left:sidebarCollapsed?80:390,right:90},maxZoom:13,duration:650});
}

function updateAddPointButton(){
  const sessionBtn=$('addPointSessionBtn'),modeBtn=$('pointModeBtn');
  pointCountEl.textContent=String(points.length);
  const atMultiLimit=pointInputMode==='multi'&&points.length>=MAX_POINTS;
  if(sessionBtn){
    sessionBtn.classList.toggle('active',addingPoints);
    sessionBtn.classList.toggle('cancel-mode',addingPoints);
    sessionBtn.disabled=!addingPoints&&atMultiLimit;
    sessionBtn.innerHTML=addingPoints
      ? '<i data-lucide="check"></i>Selesai'
      : (atMultiLimit?'<i data-lucide="circle-check"></i>Maksimal 10 Titik':'<i data-lucide="crosshair"></i>Mulai Tambah');
    sessionBtn.setAttribute('aria-pressed',addingPoints?'true':'false');
  }
  if(modeBtn){
    const multi=pointInputMode==='multi';
    modeBtn.classList.toggle('active',multi);
    modeBtn.innerHTML=multi?'<i data-lucide="list-plus"></i>Multi Titik':'<i data-lucide="map-pin"></i>Satu Titik';
    modeBtn.setAttribute('aria-pressed',multi?'true':'false');
    modeBtn.setAttribute('aria-label',multi?'Ubah ke mode satu titik':'Ubah ke mode multi titik');
  }
  const badge=$('pointModeBadge');if(badge)badge.textContent=pointInputMode==='multi'?'Mode multi titik':'Mode satu titik';
  const mapBadge=$('mapModeIndicator'),mapText=$('mapModeIndicatorText');
  if(mapBadge&&mapText){
    const multi=pointInputMode==='multi';
    mapBadge.classList.toggle('multi',multi);mapBadge.classList.toggle('single',!multi);
    mapBadge.classList.toggle('adding',addingPoints);
    mapText.textContent=multi?`Multi titik${points.length?` · ${points.length}`:''}`:'Satu titik';
  }
  restoreMapCursor();
  if(sessionBtn)refreshIcons(sessionBtn);if(modeBtn)refreshIcons(modeBtn);if(mapBadge)refreshIcons(mapBadge);
}
function showUndoDelete(snapshot){
  clearTimeout(undoDeleteTimer);undoDeleteState=snapshot;const toast=$('undoToast');$('undoToastText').textContent=`${snapshot.point.label?.trim()||snapshot.point.point_id} dihapus.`;toast.classList.remove('hidden');
  undoDeleteTimer=setTimeout(()=>{toast.classList.add('hidden');undoDeleteState=null;},5000);
}
async function deletePointWithoutRedelineation(id){
  const index=points.findIndex(p=>p.point_id===id);if(index<0)return;
  const point=points[index];const result=batchResult?.results?.find(r=>r.point_id===id)||null;const color=POINT_COLORS[id];const draft=pointNameDraft(id);
  pointNameDrafts.delete(id);pointNameSaving.delete(id);window.invalidateHssForPoint?.(id);points.splice(index,1);if(batchResult?.results)batchResult.results=batchResult.results.filter(r=>r.point_id!==id);activePointId=points[Math.min(index,points.length-1)]?.point_id||null;renderRequestedPoints();renderPointCards();
  try{if(points.length&&batchResult?.results?.length)await reconcileCachedResults();else clearResults();setStatus('Titik dihapus','success');}catch(err){setStatus(err?.message||String(err),'error');}
  persistState();showUndoDelete({point,result,color,index,draft});
}
async function undoDelete(){
  const snap=undoDeleteState;if(!snap)return;clearTimeout(undoDeleteTimer);$('undoToast').classList.add('hidden');undoDeleteState=null;
  points.splice(Math.min(snap.index,points.length),0,snap.point);POINT_COLORS[snap.point.point_id]=snap.color;pointNameDrafts.set(snap.point.point_id,snap.draft??pointName(snap.point.point_id));if(snap.result){if(!batchResult)batchResult={results:[],network_analysis:null};batchResult.results.push(snap.result);}
  activePointId=snap.point.point_id;renderRequestedPoints();renderPointCards();try{if(batchResult?.results?.length)await reconcileCachedResults();else await runBatchDelineation({fit:false});setStatus('Penghapusan dibatalkan.','success');}catch(err){setStatus(err?.message||String(err),'error');}persistState();
}

function destroyPointListSortable(){
  if(pointListSortable){
    try{pointListSortable.destroy();}catch(_){}
    pointListSortable=null;
  }
}
function persistSortablePointOrder(){
  const ids=[...pointListEl.querySelectorAll('.point-card[data-point-id]')].map(card=>card.dataset.pointId);
  if(ids.length!==points.length)return false;

  const byId=new Map(points.map(p=>[p.point_id,p]));
  const reordered=ids.map(id=>byId.get(id)).filter(Boolean);
  if(reordered.length!==points.length)return false;

  const changed=reordered.some((p,index)=>p.point_id!==points[index]?.point_id);
  if(!changed)return false;

  points=reordered;
  activePointId=null;
  persistState();
  renderRequestedPoints();
  setStatus('Urutan hasil DTA diperbarui.','success');
  return true;
}
function initPointListSortable(){
  destroyPointListSortable();
  if(!window.Sortable||!pointListEl||points.length<2)return;

  pointListSortable=window.Sortable.create(pointListEl,{
    animation:150,

    // Only collapsed result cards can be reordered.
    draggable:'.point-card:not([open])',

    // Hold 0.5 second before reorder starts.
    delay:500,
    delayOnTouchOnly:false,

    // Keep buttons/editors/actions interactive.
    filter:'button,input,select,textarea,a,.point-name-editor,.point-action-row,.point-card[open]',
    preventOnFilter:false,

    // Minimal SortableJS configuration. Native strategy is used.
    chosenClass:'point-card-sortable-ready',
    ghostClass:'point-card-sortable-ghost',
    dragClass:'point-card-sortable-drag',

    onChoose:evt=>{
      clearDtaHover();
      evt.item?.classList.add('point-card-sortable-ready');
    },
    onStart:evt=>{
      evt.item?.classList.remove('point-card-sortable-ready');
      pointListEl.classList.add('is-sortable-reordering');
    },
    onUnchoose:evt=>{
      evt.item?.classList.remove('point-card-sortable-ready');
      pointListEl.classList.remove('is-sortable-reordering');
    },
    onEnd:()=>{
      pointListEl.classList.remove('is-sortable-reordering');

      // Prevent <summary> from opening immediately after a completed reorder.
      suppressCardToggleUntil=Date.now()+450;

      const changed=persistSortablePointOrder();

      // Re-render after SortableJS finishes its own DOM cleanup.
      // Result cards remain collapsed.
      if(changed){
        setTimeout(()=>{
          renderPointCards();
          pointListEl.querySelectorAll('.point-card').forEach(card=>card.open=false);
          activePointId=null;
          applyDtaHighlight();
        },0);
      }
    }
  });
}
function renderPointCards(){
  pointCountEl.textContent=String(points.length);updateAddPointButton();
  if(!points.length){pointListEl.innerHTML='<div class="empty-state">Belum ada hasil delineasi.</div>';window.refreshHssUiState?.();return;}
  pointListEl.innerHTML=points.map((p)=>{
    const r=pointResult(p.point_id),processing=processingPointIds.has(p.point_id);
    const river=riverNameForUi(r?.official_river?.name),basin=r?.official_basin?.name||r?.requested_official_basin?.name||'—';
    const area=r?`${formatArea(r.area_km2)} km²`:(processing?'':'…');const displayId=pointName(p.point_id);const uiState=resultUiStatus(r,processing);
    const warningBadge=uiState?.cls==='warning'?`<em class="result-state-badge warning">${escapeHtml(uiState.label)}</em>`:'';
    const identityMeta=processing?'<span class="result-skeleton skeleton-wide"></span>':`<strong class="point-summary-river">${escapeHtml(river)}</strong><span class="point-summary-basin">DAS ${escapeHtml(basin)}</span>${warningBadge}`;
    const areaHtml=processing?'<span class="result-skeleton skeleton-area"></span>':area;
    const coordText=pointCoordinateText(p.point_id),draft=pointNameDraft(p.point_id),state=pointNameState(p.point_id),color=POINT_COLORS[p.point_id];
    return `<details class="point-card" data-point-id="${p.point_id}" style="--point-color:${color}" ${activePointId===p.point_id?'open':''}>
      <summary><span class="point-name-chip" style="background:${color};color:${readableTextColor(color)}">${escapeHtml(displayId)}</span><span class="point-summary-main">${identityMeta}</span><span class="point-summary-area">${areaHtml}</span><span class="point-chevron"><i data-lucide="chevron-down"></i></span></summary>
      <div class="point-body">
        <label class="point-edit-label point-name-editor ${state==='dirty'?'is-dirty':''} ${state==='saving'?'is-saving':''}" data-id="${p.point_id}"><span class="point-edit-label-row"><span>Nama titik</span><span class="point-name-state unsaved-indicator ${state==='saved'?'hidden':''}" aria-live="polite">${state==='saving'?'Menyimpan...':'Belum disimpan'}</span></span>
          <div class="point-name-grid"><input class="rename-point ${state==='dirty'?'is-dirty':''}" data-id="${p.point_id}" data-saved-value="${escapeHtml(displayId)}" value="${escapeHtml(draft)}" maxlength="25"><button class="mini-button save-name save-icon-button" data-id="${p.point_id}" aria-label="Simpan nama titik" ${state==='dirty'?'':'disabled'}>${state==='saving'?'<i data-lucide="loader-circle" class="spin-icon"></i>':'<i data-lucide="save"></i>'}</button></div><span class="point-name-limit-warning hidden">Maksimal 25 karakter.</span>
        </label>
        <div class="point-action-label">Aksi</div>
        <div class="point-action-row">${renderSidebarDtaActions(p.point_id,coordText)}</div>
        <button class="morphometry-analysis-button open-hydrologic-analysis" data-id="${p.point_id}" type="button"><i data-lucide="chart-no-axes-combined"></i><span>Karakteristik</span></button>
      </div>
    </details>`;
  }).join('');
  refreshIcons(pointListEl);
  pointListEl.querySelectorAll('.point-card').forEach(card=>{
    card.addEventListener('toggle',()=>{
      if(card.open){
        if(Date.now()<suppressCardToggleUntil){card.open=false;clearActivePointIfNoOpenCard();return;}
        setActivePoint(card.dataset.pointId,{openCard:false});
        pointListEl.querySelectorAll('.point-card').forEach(other=>{if(other!==card)other.open=false;});
      }else if(activePointId===card.dataset.pointId){
        clearActivePointIfNoOpenCard();
      }
    });
  });
  pointListEl.querySelectorAll('.save-name').forEach(b=>b.addEventListener('click',()=>savePointName(b.dataset.id)));
  pointListEl.querySelectorAll('.rename-point').forEach(input=>{
    bindPointNameLimit(input);
    input.addEventListener('input',()=>setPointNameDraft(input.dataset.id,input.value));
    input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();e.stopPropagation();if(pointNameDirty(input.dataset.id))savePointName(input.dataset.id);}else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();resetPointNameDraft(input.dataset.id);input.blur();}});
  });
  pointListEl.querySelectorAll('.remove-point').forEach(b=>b.addEventListener('click',()=>deletePointWithoutRedelineation(b.dataset.id)));
  pointListEl.querySelectorAll('.zoom-outlet').forEach(b=>b.addEventListener('click',()=>zoomToOutlet(b.dataset.id)));
  pointListEl.querySelectorAll('.zoom-point').forEach(b=>b.addEventListener('click',()=>{setActivePoint(b.dataset.id,{openCard:false});zoomToPoint(b.dataset.id);}));
  pointListEl.querySelectorAll('.open-hydrologic-analysis').forEach(b=>b.addEventListener('click',()=>openHydrologicAnalysis(b.dataset.id)));
  pointListEl.querySelectorAll('.copy-point-coordinate').forEach(b=>b.addEventListener('click',e=>copyText(e.currentTarget.dataset.coordinate||pointCoordinateText(e.currentTarget.dataset.id),e.currentTarget)));
  pointListEl.querySelectorAll('.move-point').forEach(b=>b.addEventListener('click',()=>armMovePoint(b.dataset.id)));
  pointListEl.querySelectorAll('.change-point-color').forEach(b=>b.addEventListener('click',e=>openDtaColorPicker(b.dataset.id,e.currentTarget)));
  initPointListSortable();
  applyDtaHighlight();
  window.refreshHssUiState?.();
}
function zoomToPoint(id){const r=pointResult(id);if(!r)return;const b=new maplibregl.LngLatBounds();const g=r.dta_geojson;if(g.type==='Polygon')for(const ring of g.coordinates)for(const c of ring)b.extend(c);else for(const p of g.coordinates)for(const ring of p)for(const c of ring)b.extend(c);if(!b.isEmpty())map.fitBounds(b,{padding:{top:70,bottom:60,left:sidebarCollapsed?70:380,right:70},maxZoom:14,duration:550});}
function openExistingPointMenu(id){
  const p=points.find(x=>x.point_id===id);if(!p)return;
  clearLocationPreview();closePointPopup();clearDtaHover();setActivePoint(id,{openCard:false});
  const r=pointResult(id),coord=pointMapCoordinate(id);if(!coord)return;
  const river=riverNameForUi(r?.official_river?.name),basin=r?.official_basin?.name||r?.requested_official_basin?.name||'—';
  const coordinateText=pointCoordinateText(id),currentName=pointName(id),draftName=pointNameDraft(id),state=pointNameState(id),area=r?`${formatArea(r.area_km2)} km²`:'—',color=POINT_COLORS[id];
  const html=`<div class="existing-point-menu" data-point-id="${id}">
    <div class="existing-point-menu-head"><strong class="existing-point-name-chip" data-point-saved-title style="background:${color};color:${readableTextColor(color)}">${escapeHtml(currentName)}</strong><div class="existing-point-identity"><strong class="existing-point-river">${escapeHtml(river)}</strong><span class="existing-point-basin">DAS ${escapeHtml(basin)}</span></div><b class="existing-point-area">${escapeHtml(area)}</b></div>
    <label class="popup-point-name-editor point-name-editor ${state==='dirty'?'is-dirty':''} ${state==='saving'?'is-saving':''}" data-id="${id}"><span class="point-edit-label-row"><span>Nama titik</span><span class="point-name-state unsaved-indicator ${state==='saved'?'hidden':''}" aria-live="polite">${state==='saving'?'Menyimpan...':'Belum disimpan'}</span></span><div class="point-name-grid"><input class="popup-rename-point ${state==='dirty'?'is-dirty':''}" data-id="${id}" type="text" value="${escapeHtml(draftName)}" data-saved-value="${escapeHtml(currentName)}" maxlength="25"><button class="save-icon-button popup-save-name" type="button" aria-label="Simpan nama titik" ${state==='dirty'?'':'disabled'}>${state==='saving'?'<i data-lucide="loader-circle" class="spin-icon"></i>':'<i data-lucide="save"></i>'}</button></div><span class="point-name-limit-warning hidden">Maksimal 25 karakter.</span></label>
    <div class="point-action-label">Aksi</div>
    <div class="existing-point-menu-grid">${renderPopupDtaActions()}</div>
  </div>`;
  const existingPopup=new maplibregl.Popup({closeButton:true,closeOnClick:false,offset:13,className:'existing-point-popup'}).setLngLat([coord.lon,coord.lat]).setHTML(html).addTo(map);
  pointPopup=existingPopup;
  existingPopup.on('close',()=>{
    if(pointPopup===existingPopup)pointPopup=null;
    clearSnapPreview();
    resetSelectionAfterExistingPopupClose();
  });
  const el=existingPopup.getElement(),nameInput=el.querySelector('.popup-rename-point');
  el.querySelector('.popup-save-name')?.addEventListener('click',()=>savePointName(id));
  bindPointNameLimit(nameInput);
  nameInput?.addEventListener('input',()=>setPointNameDraft(id,nameInput.value));
  nameInput?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();if(pointNameDirty(id))savePointName(id);}else if(e.key==='Escape'){e.preventDefault();resetPointNameDraft(id);nameInput.blur();}});
  el.querySelector('[data-action="zoomOutlet"]')?.addEventListener('click',()=>{zoomToOutlet(id);closePointPopup();});
  el.querySelector('[data-action="zoomDta"]')?.addEventListener('click',()=>{zoomToPoint(id);closePointPopup();});
  el.querySelector('[data-action="analysis"]')?.addEventListener('click',()=>{closePointPopup();openHydrologicAnalysis(id);});
  el.querySelector('[data-action="copyCoordinate"]')?.addEventListener('click',e=>copyText(coordinateText,e.currentTarget));
  el.querySelector('[data-action="moveOutlet"]')?.addEventListener('click',()=>armMovePoint(id));
  el.querySelector('[data-action="changeColor"]')?.addEventListener('click',e=>openDtaColorPicker(id,e.currentTarget));
  el.querySelector('[data-action="delete"]')?.addEventListener('click',async()=>{closePointPopup();await deletePointWithoutRedelineation(id);});
  syncPointNameEditors(id);refreshIcons(el);
}

function renderRelationship(net){
  if(!net||points.length<2){relationshipPanel.classList.add('hidden');relationshipContent.innerHTML='';return;}
  relationshipPanel.classList.remove('hidden');
  if(net.same_flow_path_all){relationshipContent.innerHTML=`<div class="chain-box"><b>Satu aliran:</b> ${net.ordered_points.map(pointName).join(' → ')}<div class="segment-list">${net.segments.map(s=>`<div><span>${escapeHtml(pointName(s.upstream_point))} → ${escapeHtml(pointName(s.downstream_point))}</span><strong>+${formatArea(s.incremental_area_km2)} km²</strong></div>`).join('')}</div></div>`;}
  else relationshipContent.innerHTML='<div class="chain-box">Titik berada pada cabang atau DAS yang berbeda. Setiap DTA dihitung secara terpisah dan arsiran hanya menampilkan area incremental yang tidak bertumpuk.</div>';
}

function clearLocationPreview(){
  locationPreview=null;
  if(locationPreviewPopup){try{locationPreviewPopup.remove();}catch(_){}locationPreviewPopup=null;}
  const src=map.getSource?.('location-preview');if(src)try{src.setData(emptyFC());}catch(_){}
}
function locationPreviewTitle(source,label){
  if(label)return String(label).split(',')[0].trim()||'Lokasi pilihan';
  return source==='coordinate'?'Koordinat pilihan':'Lokasi pilihan';
}
function showLocationPreview(lon,lat,source='search',label=null){
  clearLocationPreview();closePointPopup();cancelScheduledPointPopup();
  locationPreview={lon:Number(lon),lat:Number(lat),source,label};
  const src=map.getSource?.('location-preview');
  if(src)src.setData({type:'FeatureCollection',features:[{type:'Feature',properties:{},geometry:{type:'Point',coordinates:[Number(lon),Number(lat)]}}]});
  const title=locationPreviewTitle(source,label),coord=`${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}`;
  locationPreviewPopup=new maplibregl.Popup({closeButton:true,closeOnClick:false,offset:13,className:'location-preview-popup'})
    .setLngLat([Number(lon),Number(lat)])
    .setHTML(`<div class="location-preview-card"><strong>${escapeHtml(title)}</strong><span>${coord}</span><p>Lokasi pratinjau. Tekan <b>Mulai Tambah</b> untuk menggunakan lokasi ini sebagai kandidat outlet.</p></div>`)
    .addTo(map);
  locationPreviewPopup.on('close',()=>{locationPreviewPopup=null;locationPreview=null;const ps=map.getSource?.('location-preview');if(ps)try{ps.setData(emptyFC());}catch(_){}});
  setStatus('Lokasi ditampilkan sebagai pratinjau. Tekan Mulai Tambah untuk delineasi.','neutral');
  refreshIcons(locationPreviewPopup.getElement?.());
}
function consumeLocationPreview(){
  if(!locationPreview)return false;
  const candidate={...locationPreview};
  clearLocationPreview();
  openPointPopup(candidate.lon,candidate.lat,candidate.source,candidate.label);
  return true;
}

async function checkLocation(lon,lat,{signal=null}={}){
  const radius=Number(snapRadiusEl?.value||300);
  const r=await fetch(
    `/api/location-check?lon=${encodeURIComponent(lon)}&lat=${encodeURIComponent(lat)}&snap_radius_m=${encodeURIComponent(radius)}`,
    signal?{signal}:undefined
  );
  if(!r.ok)return null;
  return r.json();
}
async function openPointPopup(lon,lat,source='map',searchLabel=null,{moveTargetId=null}={}){
  // A new candidate supersedes every older unconfirmed candidate.
  closePointPopup();
  cancelScheduledPointPopup();

  const requestSerial=++pointPopupRequestSerial;
  const controller=new AbortController();
  pointPopupAbortController=controller;

  const isCurrentRequest=()=>requestSerial===pointPopupRequestSerial&&!controller.signal.aborted;
  const isMove=Boolean(moveTargetId);
  if(!isMove&&!addingPoints){showLocationPreview(lon,lat,source,searchLabel);return;}
  const targetId=isMove?moveTargetId:(pointInputMode==='multi'?nextPointId():'O1');
  if(!targetId){
    if(isCurrentRequest())pointPopupAbortController=null;
    setStatus('Maksimal 10 DTA per pemrosesan.','error');
    return;
  }

  let check=null;
  try{
    check=await checkLocation(lon,lat,{signal:controller.signal});
  }catch(err){
    // Abort is expected when the user clicks another location quickly.
    if(err?.name==='AbortError'||!isCurrentRequest())return;
    pointPopupAbortController=null;
    setStatus('Lokasi belum dapat divalidasi. Coba lagi.','error');
    return;
  }

  // A slow response from an older click must never create an orphan popup.
  if(!isCurrentRequest())return;
  pointPopupAbortController=null;
  if(!isMove&&!addingPoints)return;

  if(!check){setStatus('Lokasi belum dapat divalidasi. Coba lagi.','error');return;}
  if(check?.warning?.code==='karst_detected'){if(isMove)cancelMovePoint();showKarst({...check.warning,official_basin:check.official_basin});return;}
  if(check?.warning?.code==='outside_region'||check?.mode==='outside_region'){if(isMove)cancelMovePoint();showOutside();return;}

  const basin=check?.official_basin?.name?`DAS ${check.official_basin.name}`:'Wilayah belum teridentifikasi';
  const river=riverNameForUi(check?.official_river?.name);
  const currentPoint=isMove?points.find(p=>p.point_id===targetId):null;
  const automaticName=clampPointName(check?.toponym?.name||'');
  const suggestedName=clampPointName(automaticName||(isMove?(currentPoint?.label||targetId):targetId));
  const topInfo=check?.toponym
    ? `<div class="point-toponym-note">Nama otomatis: <b>${escapeHtml(check.toponym.name)}</b> jarak ${formatDistance(check.toponym.distance_m||0)}</div>`
    : '';

  if(!isCurrentRequest())return;

  const snap=check?.snap_preview;
  const snapped=snap?.available&&Number.isFinite(Number(snap.lon))&&Number.isFinite(Number(snap.lat))
    ? {lon:Number(snap.lon),lat:Number(snap.lat)}
    : null;
  renderSnapPreview({lon,lat},snapped);
  const snapDistance=Number(snap?.distance_m||0);
  const farSnap=Boolean(snapped&&snapDistance>snapWarningThreshold(snapRadiusEl?.value));
  const nearExcludeId=isMove?targetId:(pointInputMode==='single'&&points.some(p=>p.point_id==='O1')?'O1':null);
  const nearExisting=nearestExistingPoint(lon,lat,{excludeId:nearExcludeId});
  const tooClose=Boolean(nearExisting&&nearExisting.distance_m<100);
  const snapUnavailable=snap&&snap.available===false;

  const snapInfo=snapped
    ? `<div class="snap-info-row"><i data-lucide="git-commit-horizontal"></i><span>Titik aliran ${snapDistance>.5?`berjarak <b>${formatDistance(snapDistance)}</b> dari titik pilihan`:'berada pada titik pilihan'}</span></div>`
    : (snapUnavailable?`<div class="point-inline-warning"><i data-lucide="triangle-alert"></i><span>${escapeHtml(snap.message||'Jalur aliran tidak ditemukan dalam radius pencarian.')}</span></div>`:'');

  const warnings=[
    farSnap?`Titik akan digeser ${formatDistance(snapDistance)} ke jalur aliran terdekat.`:'',
    tooClose?`Titik terlalu dekat dengan ${escapeHtml(pointName(nearExisting.point.point_id))} (${formatDistance(nearExisting.distance_m)}). Gunakan titik yang sudah ada atau pilih lokasi lain.`:''
  ].filter(Boolean);
  const warningHtml=warnings.length
    ? `<div class="point-inline-warning"><i data-lucide="triangle-alert"></i><span>${warnings.join(' ')}</span></div>`
    : '';

  const coordText=`${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  const snappedCoord=snapped&&snapDistance>.5
    ? `<div class="point-snapped-coord">Titik aliran: ${snapped.lat.toFixed(6)}, ${snapped.lon.toFixed(6)}</div>`
    : '';
  const confirmText=isMove?'Pindahkan':'Delineasi';
  const html=`<div class="point-popup">
    <strong>${isMove?'Pindahkan Titik':'Tambahkan Titik'}</strong>
    <div class="point-coordinate-row"><span class="point-coords">${coordText}</span><button class="copy-coordinate-btn" type="button" aria-label="Salin"><i data-lucide="copy"></i></button></div>
    ${snappedCoord}
    <div class="point-basin"><b>${escapeHtml(river)}</b><span>${escapeHtml(basin)}</span></div>
    ${snapInfo}${warningHtml}
    <label>Nama titik<input id="popupPointName" type="text" value="${escapeHtml(suggestedName)}" maxlength="25"><span class="point-name-limit-warning hidden">Maksimal 25 karakter.</span></label>
    ${topInfo}
    <div class="point-actions-popup"><button class="point-cancel" type="button">Batal</button><button class="point-confirm" type="button" ${(snapUnavailable||tooClose)?'disabled':''}>${confirmText}</button></div>
  </div>`;
  if(!isCurrentRequest())return;
  const pendingPopup=new maplibregl.Popup({
    closeButton:false,
    closeOnClick:false,
    offset:12,
    className:'pending-point-popup'
  }).setLngLat([lon,lat]).setHTML(html).addTo(map);
  pointPopup=pendingPopup;
  pendingPopup.on('close',()=>{
    if(pointPopup===pendingPopup)pointPopup=null;
    clearSnapPreview();
  });
  const el=pendingPopup.getElement();
  el.querySelector('.copy-coordinate-btn')?.addEventListener('click',e=>copyText(coordText,e.currentTarget));
  el.querySelector('.point-cancel').addEventListener('click',()=>{closePointPopup();if(isMove)cancelMovePoint();});
  const confirmBtn=el.querySelector('.point-confirm');
  const confirmAction=async()=>{
    if(confirmBtn.disabled)return;
    const label=clampPointName(el.querySelector('#popupPointName').value.trim()||targetId);
    if(isMove){
      const existing=points.find(p=>p.point_id===targetId);if(!existing)return;
      const previousPoint={...existing};
      const previousBatch=batchResult;
      existing.lon=lon;existing.lat=lat;existing.source=source;existing.label=label;
      if(previousBatch?.results?.length){
        const remaining=previousBatch.results.filter(r=>r.point_id!==targetId);
        batchResult=remaining.length?{...previousBatch,results:remaining,network_analysis:null}:null;
      }
      movePointId=null;try{map.getCanvas().style.cursor='';}catch(_){}closePointPopup();activePointId=targetId;
      renderDtaLayers();renderRequestedPoints();renderPointCards();persistState();
      const moved=await runBatchDelineation({fit:false,onlyPointId:targetId});
      if(moved===true){zoomToOutlet(targetId);}else if(moved===false){
        Object.assign(existing,previousPoint);batchResult=previousBatch;renderDtaLayers();renderRequestedPoints();renderPointCards();renderRelationship(previousBatch?.network_analysis||null);persistState();
      }
    }else if(pointInputMode==='multi'){
      if(points.length>=MAX_POINTS)return;
      points.push({point_id:targetId,lon,lat,source,label});pointNameDrafts.set(targetId,label||targetId);
      activePointId=targetId;closePointPopup();renderRequestedPoints();renderPointCards();persistState();
      await runBatchDelineation({fit:points.length===1,onlyPointId:targetId});
    }else{
      points=[{point_id:'O1',lon,lat,source,label}];pointNameDrafts.clear();pointNameDrafts.set('O1',label||'O1');batchResult=null;activePointId='O1';closePointPopup();renderRequestedPoints();renderPointCards();persistState();
      await runBatchDelineation({fit:true});
    }
  };
  confirmBtn.addEventListener('click',confirmAction);
  const pendingNameInput=el.querySelector('#popupPointName');
  bindPointNameLimit(pendingNameInput);
  pendingNameInput?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();confirmAction();}else if(e.key==='Escape'){e.preventDefault();closePointPopup();if(isMove)cancelMovePoint();}});
  refreshIcons(el);
}

function showKarst(detail){$('karstMessage').textContent=detail?.message||KARST_MESSAGE;const basin=detail?.official_basin?.name||detail?.official_basin?.basin_name||'';$('karstBasin').textContent=basin?`DAS ${basin}`:'';openMapModal($('karstModal'));}
function showOutside(){openMapModal($('outsideModal'));}

function measureLength(coords){let total=0;for(let i=1;i<coords.length;i++){const [a,b]=[coords[i-1],coords[i]],R=6371008.8,p1=a[1]*Math.PI/180,p2=b[1]*Math.PI/180,dp=(b[1]-a[1])*Math.PI/180,dl=(b[0]-a[0])*Math.PI/180;const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;total+=2*R*Math.atan2(Math.sqrt(h),Math.sqrt(1-h));}return total;}
function updateMeasure(preview=null){if(!map.getSource('measure-line'))return;const c=preview&&measureCoords.length?[...measureCoords,preview]:[...measureCoords];const line=c.length>=2?{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:c}}:null;map.getSource('measure-line').setData({type:'FeatureCollection',features:line?[line]:[]});map.getSource('measure-points').setData({type:'FeatureCollection',features:measureCoords.map((x,i)=>({type:'Feature',properties:{n:i+1},geometry:{type:'Point',coordinates:x}}))});$('measureText').textContent=!measureCoords.length?'Klik titik pertama pada peta.':c.length<2?'Klik titik berikutnya.':`Jarak: ${formatDistance(measureLength(c))}${measureMode?' • klik untuk menambah titik':''}`;}
function setMeasureMode(on){measureMode=on;$('measureBtn').classList.toggle('active',on);$('measurePanel').classList.toggle('hidden',!on&&!measureCoords.length);setStatus(on?'Mode penggaris aktif. Klik peta untuk menambah titik.':'Penggaris selesai.','neutral');}
function clearMeasure(){measureCoords=[];measurePreview=null;updateMeasure();$('measurePanel').classList.add('hidden');setMeasureMode(false);}

function setHeaderVisible(visible){
  const h=$('appHeader'),btn=$('headerHandle');if(!h||!btn)return;
  clearTimeout(headerHideTimer);
  h.classList.toggle('is-hidden',!visible);
  btn.innerHTML=visible?'<i id="headerHandleIcon" data-lucide="chevron-up"></i>':'<i id="headerHandleIcon" data-lucide="chevron-down"></i>';
  btn.setAttribute('aria-label',visible?'Sembunyikan header':'Tampilkan header');
  btn.setAttribute('aria-expanded',visible?'true':'false');
  // The shell keeps this toggle aligned with the search box at the top-right.
  refreshIcons(btn);
  setTimeout(()=>map.resize(),80);
}
function showHeader({autoHide=true}={}){
  if(isHeaderUiBlocked())return;
  setHeaderVisible(true);
  if(autoHide){
    clearTimeout(headerHideTimer);
    headerHideTimer=setTimeout(()=>setHeaderVisible(false),2800);
  }
}
function hideHeaderSoon(){
  clearTimeout(headerHideTimer);
  headerHideTimer=setTimeout(()=>setHeaderVisible(false),1200);
}
function toggleHeader(){
  if(isHeaderUiBlocked())return;
  const hidden=$('appHeader')?.classList.contains('is-hidden');
  if(hidden)showHeader({autoHide:false});
  else setHeaderVisible(false);
}
function setSidebarCollapsed(on,{save=true}={}){sidebarCollapsed=on;$('sidebar').classList.toggle('collapsed',on);document.querySelector('.webgis-shell').classList.toggle('sidebar-is-collapsed',on);const b=$('sidebarSearchToggle');if(b)b.innerHTML=on?'<i data-lucide="panel-left-open"></i>':'<i data-lucide="panel-left-close"></i>';refreshIcons();setTimeout(()=>map.resize(),220);if(save)persistState();}

map.on('style.load',addOperationalLayers);
map.on('load',async()=>{
  try{info=await fetch('/api/info').then(r=>r.json());studyBounds=[[info.bounds_wgs84[0],info.bounds_wgs84[1]],[info.bounds_wgs84[2],info.bounds_wgs84[3]]];if(!restoredState.camera)map.fitBounds(studyBounds,{padding:40,maxZoom:8});}catch(_){setStatus('Data siap digunakan.','neutral');}
  setSidebarCollapsed(sidebarCollapsed,{save:false});setHeaderVisible(false);applyBasemapVisibility();renderRequestedPoints();renderPointCards();refreshIcons();
  if(points.length)await runBatchDelineation({fit:false});
});
map.on('mousemove',e=>{
  $('coordReadout').textContent=`${e.lngLat.lat.toFixed(6)}, ${e.lngLat.lng.toFixed(6)}`;
  if(measureMode&&measureCoords.length){measurePreview=[e.lngLat.lng,e.lngLat.lat];updateMeasure(measurePreview);clearDtaHover();return;}
  if(isHeaderUiBlocked()||pointPopup||progressiveMoving){clearDtaHover();return;}

  let pointFeature=null,dtaFeature=null;
  try{pointFeature=map.queryRenderedFeatures(e.point,{layers:['requested-points']})?.[0]||null;}catch(_){}
  if(pointFeature?.properties?.point_id){
    map.getCanvas().style.cursor='pointer';
    queueDtaHover(pointFeature.properties.point_id,e.lngLat,'point');
    return;
  }

  const hitLayers=[];
  for(let i=1;i<=MAX_POINTS;i++){const layer=`dta-O${i}-hit`;if(map.getLayer(layer))hitLayers.push(layer);}
  if(hitLayers.length){
    try{
      const hits=map.queryRenderedFeatures(e.point,{layers:hitLayers})||[];
      if(hits.length)dtaFeature=(activePointId&&hits.find(f=>f.properties?.point_id===activePointId))||hits[0];
    }catch(_){}
  }
  if(dtaFeature?.properties?.point_id){
    if(addingPoints){clearDtaHover();restoreMapCursor();}
    else{map.getCanvas().style.cursor='pointer';queueDtaHover(dtaFeature.properties.point_id,e.lngLat,'dta');}
  }else clearDtaHover();
});
map.on('mouseout',()=>{clearDtaHover();restoreMapCursor();if(measureMode){measurePreview=null;updateMeasure();}});
map.on('dragstart',()=>{try{map.getCanvas().style.cursor='grabbing';}catch(_){}});
map.on('dragend',()=>restoreMapCursor());
map.on('movestart',()=>{closeDtaColorPicker();setProgressiveMoving(true);});
map.on('moveend',()=>{setProgressiveMoving(false);persistState();});
map.on('click',e=>{
  clearDtaHover();
  hideHeaderSoon();

  // A visible result popup consumes the first outside-map click.
  // This prevents an accidental new/add/move-point action while closing it.
  if(isExistingPointPopupOpen()){
    closePointPopup();
    return;
  }

  if(measureMode){
    cancelScheduledPointPopup();
    cancelPointPopupValidation();
    measureCoords.push([e.lngLat.lng,e.lngLat.lat]);
    updateMeasure();
    return;
  }

  if(movePointId){
    schedulePointPopupFromMap(e.lngLat.lng,e.lngLat.lat,{moveTargetId:movePointId});
    return;
  }

  let marker=null;
  try{marker=map.queryRenderedFeatures(e.point,{layers:['requested-points']})?.[0]||null;}catch(_){}
  if(marker?.properties?.point_id){
    cancelScheduledPointPopup();
    cancelPointPopupValidation();
    openExistingPointMenu(marker.properties.point_id);
    return;
  }

  const dtaHitLayers=[];for(let i=1;i<=MAX_POINTS;i++){const layer=`dta-O${i}-hit`;if(map.getLayer(layer))dtaHitLayers.push(layer);}
  let dtaHit=null;
  if(dtaHitLayers.length){try{const hits=map.queryRenderedFeatures(e.point,{layers:dtaHitLayers})||[];dtaHit=(activePointId&&hits.find(f=>f.properties?.point_id===activePointId))||hits[0]||null;}catch(_){}}
  if(!addingPoints){
    cancelScheduledPointPopup();cancelPointPopupValidation();
    if(dtaHit?.properties?.point_id)openExistingPointMenu(dtaHit.properties.point_id);
    return;
  }

  // During an explicit add-point session every non-outlet map click is a candidate,
  // including clicks over an existing DTA polygon.
  schedulePointPopupFromMap(e.lngLat.lng,e.lngLat.lat);
});
map.on('dblclick',e=>{
  // Double-click is navigation, not a request to create multiple candidate points.
  cancelScheduledPointPopup();
  cancelPointPopupValidation();
  if(pointPopup?.getElement?.()?.classList?.contains('pending-point-popup'))closePointPopup();
  if(measureMode){e.preventDefault();setMeasureMode(false);}
});

$('mapSearchForm').addEventListener('submit',async e=>{e.preventDefault();const q=$('searchInput').value.trim();if(q.length<2){setStatus('Masukkan minimal 2 karakter.','error');return;}searchResultsEl.classList.remove('hidden');searchResultsEl.innerHTML='<div class="search-loading">Mencari…</div>';try{const r=await fetch(`/api/geocode?q=${encodeURIComponent(q)}`),p=await r.json();if(!r.ok)throw new Error(parseApiError(p,'Pencarian gagal.').message);if(!p.results.length){searchResultsEl.innerHTML='<div class="search-empty">Lokasi tidak ditemukan.</div>';return;}searchResultsEl.innerHTML=p.results.map((x,i)=>`<button class="search-result" type="button" data-i="${i}"><strong>${escapeHtml(x.name||x.display_name.split(',')[0])}</strong><span>${escapeHtml(x.display_name)}</span></button>`).join('');searchResultsEl.querySelectorAll('.search-result').forEach(b=>b.addEventListener('click',()=>{const x=p.results[Number(b.dataset.i)];searchResultsEl.classList.add('hidden');map.flyTo({center:[x.lon,x.lat],zoom:13});cancelScheduledPointPopup();if(addingPoints){clearLocationPreview();openPointPopup(Number(x.lon),Number(x.lat),x.source||'geocode',x.display_name);}else showLocationPreview(Number(x.lon),Number(x.lat),x.source||'geocode',x.display_name);}));}catch(err){searchResultsEl.innerHTML=`<div class="search-empty">${escapeHtml(err.message)}</div>`;}});
$('previewCoordinateBtn').addEventListener('click',()=>{try{const {lat,lon}=parseCoordinate($('coordinateInput').value);map.flyTo({center:[lon,lat],zoom:13});cancelScheduledPointPopup();if(addingPoints){clearLocationPreview();openPointPopup(lon,lat,'coordinate');}else showLocationPreview(lon,lat,'coordinate');}catch(err){setStatus(err.message,'error');}});
$('decimalSeparatorSelect')?.addEventListener('change',event=>{decimalSeparator=event.target.value==='.'?'.':',';persistState();renderPointCards();if(!$('hydrologicAnalysisModal').classList.contains('hidden')&&activePointId)openHydrologicAnalysis(activePointId);});
$('coordinateInput').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();$('previewCoordinateBtn').click();}});
$('addPointSessionBtn').addEventListener('click',()=>{
  if(!addingPoints&&pointInputMode==='multi'&&points.length>=MAX_POINTS)return;
  addingPoints=!addingPoints;
  if(addingPoints){if(isExistingPointPopupOpen())closePointPopup();clearDtaHover();}
  if(!addingPoints){
    cancelScheduledPointPopup();cancelPointPopupValidation();
    if(pointPopup?.getElement?.()?.classList?.contains('pending-point-popup'))closePointPopup({cancelPending:false});
    clearSnapPreview();
  }
  updateAddPointButton();persistState();setStatus(interactionStatusText(),'neutral');
  if(addingPoints)consumeLocationPreview();
});
$('pointModeBtn').addEventListener('click',()=>{
  pointInputMode=pointInputMode==='single'?'multi':'single';
  if(pointInputMode==='multi'&&points.length>=MAX_POINTS&&addingPoints){addingPoints=false;cancelScheduledPointPopup();cancelPointPopupValidation();if(pointPopup?.getElement?.()?.classList?.contains('pending-point-popup'))closePointPopup({cancelPending:false});}
  updateAddPointButton();persistState();
  if(pointInputMode==='multi')showMultiModeHintOnce();
  setStatus(interactionStatusText(),'neutral');
});
$('clearAllBtn').addEventListener('click',()=>{if(points.length)openMapModal($('confirmClearModal'));});
$('confirmClearBtn').addEventListener('click',()=>{cancelScheduledPointPopup();cancelPointPopupValidation();closePointPopup({cancelPending:false});points=[];pointNameDrafts.clear();pointNameSaving.clear();batchResult=null;addingPoints=false;clearLocationPreview();activePointId=null;clearTimeout(undoDeleteTimer);undoDeleteState=null;$('undoToast').classList.add('hidden');renderRequestedPoints();clearResults();updateAddPointButton();closeMapModal($('confirmClearModal'));persistState();});
for(const id of ['closeClearModal','cancelClearBtn'])$(id).addEventListener('click',()=>closeMapModal($('confirmClearModal')));
snapRadiusEl.addEventListener('change',()=>{persistState();if(points.length)runBatchDelineation({fit:false});});boundaryMatchEl.addEventListener('change',()=>{persistState();if(points.length)runBatchDelineation({fit:false});});
$('sidebarSearchToggle').addEventListener('click',e=>{e.preventDefault();e.stopPropagation();setSidebarCollapsed(!sidebarCollapsed);});
$('zoomInBtn').addEventListener('click',()=>map.zoomIn());$('zoomOutBtn').addEventListener('click',()=>map.zoomOut());$('resetNorthBtn').addEventListener('click',()=>map.easeTo({bearing:0,pitch:0,duration:350}));$('fullscreenBtn').addEventListener('click',async()=>{try{if(!document.fullscreenElement)await document.documentElement.requestFullscreen();else await document.exitFullscreen();}catch(_){}});document.addEventListener('fullscreenchange',()=>{$('fullscreenBtn').innerHTML=document.fullscreenElement?'<i data-lucide="minimize"></i>':'<i data-lucide="maximize"></i>';if(document.fullscreenElement)setHeaderVisible(false);updateHeaderHandleInteractivity();refreshIcons();setTimeout(()=>map.resize(),80);});
$('homeBtn').addEventListener('click',()=>{if(studyBounds)map.fitBounds(studyBounds,{padding:45,maxZoom:8});});
$('focusAllDtaBtn')?.addEventListener('click',fitToResults);
$('measureBtn').addEventListener('click',()=>setMeasureMode(!measureMode));$('clearMeasureBtn').addEventListener('click',clearMeasure);$('layerBtn').addEventListener('click',()=>{layerPanel.classList.toggle('hidden');if(!layerPanel.classList.contains('hidden'))clearDtaHover();updateHeaderHandleInteractivity();});$('closeLayerPanel').addEventListener('click',()=>{layerPanel.classList.add('hidden');updateHeaderHandleInteractivity();});
$('basemapBtn').addEventListener('click',()=>{openMapModal($('basemapModal'));updateBasemapGallery();});$('closeBasemapModal').addEventListener('click',()=>closeMapModal($('basemapModal')));document.querySelectorAll('.basemap-card').forEach(card=>card.addEventListener('click',()=>setBasemap(card.dataset.basemap)));$('noBasemapBtn').addEventListener('click',()=>setBasemap('no-basemap'));$('showHillshade').addEventListener('change',()=>{applyLayerState();persistState();});$('hillshadeOpacity').addEventListener('input',e=>{$('hillshadeOpacityValue').textContent=`${e.target.value}%`;if(map.getLayer('esri-hillshade-layer'))map.setPaintProperty('esri-hillshade-layer','raster-opacity',Number(e.target.value)/100);schedulePersistState();});
$('showBasins').addEventListener('change',()=>{applyLayerState();persistState();});$('showBasinLabels').addEventListener('change',()=>{applyLayerState();persistState();});$('showRivers').addEventListener('change',()=>{updateRiverVisibility();persistState();});$('showRiverLabels').addEventListener('change',()=>{updateRiverVisibility();persistState();});$('autoRiverZoom').addEventListener('change',()=>{updateRiverVisibility();updateRiverDisplaySource({force:true});persistState();});document.querySelectorAll('.river-order-toggle').forEach(x=>x.addEventListener('change',()=>{updateRiverVisibility();persistState();}));
map.on('zoom',()=>updateRiverLabelFilter());
map.on('zoomend',()=>updateRiverDisplaySource());
$('basinColor').addEventListener('input',e=>{if(map.getLayer('official-basins-line'))map.setPaintProperty('official-basins-line','line-color',e.target.value);if(map.getLayer('official-basin-label'))map.setPaintProperty('official-basin-label','text-color',e.target.value);schedulePersistState();});
$('riverColor').addEventListener('input',e=>{for(const k of RIVER_KEYS){if(map.getLayer(`official-river-${k}`))map.setPaintProperty(`official-river-${k}`,'line-color',e.target.value);}if(map.getLayer('official-river-labels'))map.setPaintProperty('official-river-labels','text-color',e.target.value);schedulePersistState();});
$('showHatch').addEventListener('change',()=>{applyLayerState();updateLabelDeclutter();persistState();});$('hatchOpacity').addEventListener('input',()=>{updateHatchOpacity();schedulePersistState();});$('lineWidth').addEventListener('input',()=>{updateLineWidths();schedulePersistState();});

function resetLayerStyling(){
  $('basinColor').value=DEFAULT_BASIN_COLOR;$('riverColor').value=DEFAULT_RIVER_COLOR;
  $('hillshadeOpacity').value='100';$('hillshadeOpacityValue').textContent='100%';
  $('hatchOpacity').value='22';$('hatchOpacityValue').textContent='22%';
  $('lineWidth').value='2';$('lineWidthValue').textContent='2.0 px';
  $('showHillshade').checked=false;$('showBasins').checked=true;$('showBasinLabels').checked=true;
  $('showRivers').checked=true;$('autoRiverZoom').checked=true;$('showRiverLabels').checked=true;$('showHatch').checked=false;
  document.querySelectorAll('.river-order-toggle').forEach(x=>x.checked=true);
  if(map.getLayer('official-basins-line'))map.setPaintProperty('official-basins-line','line-color',DEFAULT_BASIN_COLOR);
  if(map.getLayer('official-basin-label'))map.setPaintProperty('official-basin-label','text-color',DEFAULT_BASIN_COLOR);
  for(const k of RIVER_KEYS){if(map.getLayer(`official-river-${k}`))map.setPaintProperty(`official-river-${k}`,'line-color',DEFAULT_RIVER_COLOR);}
  if(map.getLayer('official-river-labels'))map.setPaintProperty('official-river-labels','text-color',DEFAULT_RIVER_COLOR);
  for(let i=1;i<=MAX_POINTS;i++)setDtaColor(`O${i}`,POINT_PALETTE[i-1],{save:false});
  if(map.getLayer('esri-hillshade-layer'))map.setPaintProperty('esri-hillshade-layer','raster-opacity',1);
  updateHatchOpacity();updateLineWidths();applyLayerState();updateRiverVisibility();renderPointCards();persistState();setStatus('Tampilan layer dikembalikan ke bawaan.','success');
}
$('resetColorsBtn').addEventListener('click',resetLayerStyling);

function updateDownloadSummary(){
  const summary=$('downloadSummary');if(!summary)return;
  const formats=[...document.querySelectorAll('.download-format:checked')].map(x=>({gpkg:'GeoPackage',shp:'Shapefile',geojson:'GeoJSON',kml:'KML'}[x.value]||x.value));
  const modes=[...document.querySelectorAll('.geometry-mode:checked')].map(x=>x.value==='smoothed'?'Diperhalus':'Asli');
  const hssCount=window.getHssAnalyzedCount?.()||0;
  summary.innerHTML=`<div><b>${points.length} DTA</b><span>${modes.length?modes.join(' + '):'Belum memilih geometri'}</span></div><div><b>Format</b><span>${formats.length?formats.join(', '):'Belum dipilih'}</span></div><div><b>Jaringan sungai</b><span>${$('downloadRivers')?.checked?'Disertakan':'Tidak disertakan'}</span></div><div><b>Karakteristik DTA</b><span>${$('downloadAnalysisReport')?.checked?'PDF + XLSX per DTA':'Tidak disertakan'}</span></div><div><b>Analisis HSS</b><span>${$('downloadHss')?.checked?`PDF + XLSX untuk ${hssCount} DTA yang telah dianalisis`:'Tidak disertakan'}</span></div>`;
}

$('downloadBtn').addEventListener('click',()=>{$('downloadStatus').textContent='';updateDownloadSummary();openMapModal($('downloadModal'));});
for(const id of ['closeDownloadModal','cancelDownloadBtn'])$(id).addEventListener('click',()=>closeMapModal($('downloadModal')));
document.querySelectorAll('.download-format,.geometry-mode').forEach(x=>x.addEventListener('change',updateDownloadSummary));
$('downloadRivers')?.addEventListener('change',updateDownloadSummary);$('downloadAnalysisReport')?.addEventListener('change',updateDownloadSummary);$('downloadHss')?.addEventListener('change',updateDownloadSummary);
$('confirmDownloadBtn').addEventListener('click',async()=>{
  const formats=[...document.querySelectorAll('.download-format:checked')].map(x=>x.value);const geometry_modes=[...document.querySelectorAll('.geometry-mode:checked')].map(x=>x.value);
  if(!geometry_modes.length){$('downloadStatus').textContent='Pilih Diperhalus, Asli, atau keduanya.';return;}if(!formats.length){$('downloadStatus').textContent='Pilih minimal satu format.';return;}
  $('downloadStatus').textContent='Menyiapkan paket unduhan…';$('confirmDownloadBtn').disabled=true;
  try{const r=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({points:points.map(({point_id,lon,lat,source,label})=>({point_id,lon,lat,source,label})),snap_radius_m:Number(snapRadiusEl.value),boundary_match_m:Number(boundaryMatchEl.value),geometry_modes,formats,include_rivers:$('downloadRivers').checked,include_analysis_report:$('downloadAnalysisReport')?.checked===true,include_hss:$('downloadHss')?.checked===true,hss_results:window.getHssDownloadPayload?.()||{},language:uiLanguage,decimal_separator:decimalSeparator})});if(!r.ok){const error=await parseErrorResponse(r,'Unduhan gagal.');throw new Error(error.message);}const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');const cd=r.headers.get('content-disposition')||'';const m=cd.match(/filename="?([^";]+)"?/i);a.href=url;a.download=m?m[1]:'Delineasi_DTA.zip';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);closeMapModal($('downloadModal'));}catch(e){$('downloadStatus').textContent=e.message||String(e);}finally{$('confirmDownloadBtn').disabled=false;}
});

for(const id of ['definitionHeaderBtn','definitionSidebarBtn'])$(id).addEventListener('click',()=>openMapModal($('definitionModal')));
for(const id of ['methodologyHeaderBtn','methodologySidebarBtn'])$(id).addEventListener('click',()=>openMapModal($('methodologyModal')));
$('basinSourceBtn').addEventListener('click',()=>openMapModal($('basinSourceModal')));
$('closeDefinitionModal').addEventListener('click',()=>closeMapModal($('definitionModal')));$('closeMethodologyModal').addEventListener('click',()=>closeMapModal($('methodologyModal')));$('closeBasinSourceModal').addEventListener('click',()=>closeMapModal($('basinSourceModal')));$('closeKarstModal').addEventListener('click',()=>closeMapModal($('karstModal')));$('closeOutsideModal').addEventListener('click',()=>closeMapModal($('outsideModal')));
$('closeHydrologicAnalysisModal').addEventListener('click',()=>closeMapModal($('hydrologicAnalysisModal')));
for(const id of ['karstModal','outsideModal','confirmClearModal','downloadModal','hydrologicAnalysisModal','hssAnalysisModal','definitionModal','methodologyModal','basinSourceModal','basemapModal','usageNoticeModal'])$(id).addEventListener('click',e=>{if(e.target.id===id)closeMapModal(e.currentTarget);});
$('headerHandle').addEventListener('click',e=>{e.preventDefault();e.stopPropagation();if(isHeaderUiBlocked())return;toggleHeader();});
$('closeDtaColorPicker')?.addEventListener('click',e=>{e.preventDefault();closeDtaColorPicker();});
document.addEventListener('pointerdown',e=>{const panel=$('dtaColorPickerPanel');if(!panel||panel.classList.contains('hidden'))return;if(panel.contains(e.target)||e.target.closest?.('.change-point-color'))return;closeDtaColorPicker();});
$('appHeader').addEventListener('mouseenter',()=>clearTimeout(headerHideTimer));
$('appHeader').addEventListener('mouseleave',hideHeaderSoon);
document.addEventListener('mousemove',e=>{if(e.clientY<=8&&!isHeaderUiBlocked()&&$('appHeader')?.classList.contains('is-hidden'))showHeader();},{passive:true});
window.addEventListener('resize',()=>{const visible=!$('appHeader')?.classList.contains('is-hidden');setHeaderVisible(visible);},{passive:true});

$('undoDeleteBtn').addEventListener('click',undoDelete);
$('usageInfoBtn')?.addEventListener('click',()=>openMapModal($('usageNoticeModal')));
$('acceptUsageNotice').addEventListener('click',()=>closeMapModal($('usageNoticeModal')));
document.addEventListener('keydown',e=>{
  const tag=(e.target?.tagName||'').toLowerCase();const typing=['input','textarea','select'].includes(tag)||e.target?.isContentEditable;
  const usageVisible=!$('usageNoticeModal').classList.contains('hidden');
  if(e.key==='f'||e.key==='F'){
    if(!typing&&!usageVisible&&!document.querySelector('.modal-backdrop:not(.hidden)')&&!pointPopup&&batchResult?.results?.length){e.preventDefault();fitToResults();}
    return;
  }
  if(e.key!=='Escape')return;
  if(usageVisible)return;
  if(pointPopup){closePointPopup();if(movePointId)cancelMovePoint();return;}
  if(movePointId){cancelMovePoint();return;}
  if(measureMode){setMeasureMode(false);return;}
  const openModal=[...document.querySelectorAll('.modal-backdrop:not(.hidden)')].pop();if(openModal){closeMapModal(openModal);return;}
  if(addingPoints){addingPoints=false;cancelScheduledPointPopup();cancelPointPopupValidation();if(pointPopup?.getElement?.()?.classList?.contains('pending-point-popup'))closePointPopup({cancelPending:false});clearLocationPreview();updateAddPointButton();persistState();setStatus(interactionStatusText(),'neutral');return;}
  if(!layerPanel.classList.contains('hidden')){layerPanel.classList.add('hidden');updateHeaderHandleInteractivity();}
});
document.addEventListener('hydro:themechange',e=>{applyMapTheme(e.detail?.theme||'light');persistState();});
setSidebarCollapsed(sidebarCollapsed,{save:false});updateAddPointButton();applyInterfaceLanguage();updateBasemapGallery();refreshIcons();setHeaderVisible(false);
showUsageNoticeOncePerBrowserSession();
