/* Hidrograf Satuan Sintetis (HSS) — per-DTA analysis UI, Chart.js edition. */
(() => {
  const METHOD_DEFS = [
    {id:'scs',label:'NRCS / SCS',subtitle:'Kurva tak berdimensi SCS',params:[['Ct','Ct',1,0.05,10,0.05]]},
    {id:'nakayasu',label:'Nakayasu',subtitle:'HSS empiris dengan tiga segmen resesi',params:[['alpha','α',2,0.2,10,0.1]]},
    {id:'snyder_alexeyev',label:'Snyder–Alexeyev',subtitle:'Skala Snyder dengan bentuk kurva Alexeyev',params:[['Ct','Ct',1,0.05,10,0.05],['Cp','Cp',1,0.05,5,0.05]]},
    {id:'gama1',label:'Gama I',subtitle:'Parameter morfometri dan jaringan sungai DTA',params:[]},
    {id:'limantara',label:'Limantara',subtitle:'HSS berbasis karakteristik DTA dan kekasaran',params:[['n','n',0.05,0.005,0.5,0.005]]},
    {id:'itb1b',label:'ITB-1b',subtitle:'Kurva tunggal analitik',params:[['Ct','Ct',1,0.05,10,0.05],['Cp','Cp',1,0.05,5,0.05],['alpha','α',3.7,0.1,20,0.1],['k','Tb/Tp',10,5,20,1]]},
    {id:'itb2b',label:'ITB-2b',subtitle:'Lengkung naik dan turun terpisah',params:[['Ct','Ct',1,0.05,10,0.05],['Cp','Cp',1,0.05,5,0.05],['alpha','α',1.7,0.1,20,0.1],['beta','β',0.84,0.05,10,0.05],['k','Tb/Tp',10,5,20,1]]},
  ];
  const METHOD_COLORS = ['#223468','#D97706','#16836B','#7C4D9A','#B64E58','#2678B2','#697B2B'];
  const MORPH_FIELDS = [
    ['A','Luas DTA (A)','km²',0.000001,1000000,0.01],
    ['L','Panjang alur utama (L)','km',0.000001,10000,0.01],
    ['Lc','Panjang ke sentroid (Lc)','km',0.000001,10000,0.01],
    ['S_pct','Kemiringan alur utama (S)','%',0.000001,1000,0.001],
    ['Lt','Panjang total sungai (Lt)','km',0.000001,100000,0.01],
    ['L1','Panjang sungai orde 1 (L1)','km',0,100000,0.01],
    ['N','Jumlah segmen sungai (N)','segmen',1,1000000,1],
    ['N1','Jumlah sungai orde 1 (N1)','segmen',0,1000000,1],
    ['JN','Jumlah percabangan (JN)','percabangan',0.000001,1000000,1],
    ['WU','Lebar DTA pada ¾ L (WU)','km',0.000001,10000,0.01],
    ['WL','Lebar DTA pada ¼ L (WL)','km',0.000001,10000,0.01],
    ['AU','Luas bagian hulu (AU)','km²',0.000001,1000000,0.01],
  ];

  const hssResults = new Map();
  const hssParameters = new Map();
  const hssMorphometry = new Map();
  const hssMorphometryDefaults = new Map();
  const hssTr = new Map();
  const hssMethodSelections = new Map();
  const hssDirty = new Set();
  let currentPointId = null;
  let currentChartMethod = 'comparison';
  let chartInstance = null;

  const cloneDefaults = () => Object.fromEntries(METHOD_DEFS.map(method => [
    method.id,
    Object.fromEntries(method.params.map(([key,,value]) => [key,value]))
  ]));

  function currentPointIds(){return points.filter(p=>pointResult(p.point_id)).map(p=>p.point_id);}
  function parameterState(pointId){if(!hssParameters.has(pointId))hssParameters.set(pointId,cloneDefaults());return hssParameters.get(pointId);}
  function trState(pointId){if(!hssTr.has(pointId))hssTr.set(pointId,1);return hssTr.get(pointId);}
  function methodSelectionState(pointId){if(!hssMethodSelections.has(pointId))hssMethodSelections.set(pointId,new Set(METHOD_DEFS.map(item=>item.id)));return hssMethodSelections.get(pointId);}
  function hssNumber(value,digits=2){const number=Number(value);if(!Number.isFinite(number))return '—';const text=number.toFixed(digits);return decimalSeparator===','?text.replace('.',','):text;}
  function methodById(id){return METHOD_DEFS.find(item=>item.id===id);}
  function dtaDisplayLabel(id){
    if(typeof window.dtaAnalysisDisplayLabel==='function')return window.dtaAnalysisDisplayLabel(id);
    const result=pointResult(id),river=String(result?.official_river?.name||'').trim(),point=String(pointName(id)||id).trim();
    return river?`${river} – ${point}`:point;
  }
  window.hssDtaDisplayLabel=dtaDisplayLabel;

  function markDirty(pointId,message='Parameter berubah. Hitung ulang HSS agar hasil, PDF, dan Excel diperbarui.'){
    if(hssResults.has(pointId))hssDirty.add(pointId);
    refreshDownloadOption();renderHssDirtyState(pointId,message);
  }

  function extractedMorphometry(pointId){
    const analysis=pointResult(pointId)?.hydrologic_analysis||{};
    const morph=analysis.morphometry||{},terrain=analysis.terrain||{},drain=analysis.drainage||{},gama=drain.gama1||{},flowSlope=terrain.flowpath_slope||{};
    const A=Number(morph.area_km2),Lc=Number(terrain.centroidal_flowpath_km),longest=Number(terrain.longest_flow_path_km),networkL=Number(drain.main_channel_length_km);
    const useFlowpath=Number.isFinite(longest)&&longest>0&&(!Number.isFinite(networkL)||networkL<=0||(Number.isFinite(Lc)&&Lc>0&&networkL<Lc));
    const L=useFlowpath?longest:networkL;
    const networkSlope=Number(drain.main_channel_slope_pct),flowpathSlope=Number(flowSlope.longest_flowpath_pct);
    const S_pct=useFlowpath&&Number.isFinite(flowpathSlope)?flowpathSlope:(Number.isFinite(networkSlope)?networkSlope:flowpathSlope);
    const Lt=Number(drain.total_stream_length_km),SF=Number(gama.source_factor),SN=Number(gama.source_frequency),N=Number(drain.stream_count),RUA=Number(gama.relative_upstream_area);
    const sourceLength=Number(gama.source_stream_length_km),sourceCount=Number(gama.source_stream_count),upstreamArea=Number(gama.upstream_area_km2);
    return {
      A:Number.isFinite(A)?A:null,L:Number.isFinite(L)?L:null,Lc:Number.isFinite(Lc)?Lc:null,S_pct:Number.isFinite(S_pct)?S_pct:null,
      Lt:Number.isFinite(Lt)?Lt:null,L1:Number.isFinite(sourceLength)?sourceLength:(Number.isFinite(Lt)&&Number.isFinite(SF)?Lt*SF:null),
      N:Number.isFinite(N)?N:null,N1:Number.isFinite(sourceCount)?sourceCount:(Number.isFinite(N)&&Number.isFinite(SN)?N*SN:null),
      JN:Number.isFinite(Number(drain.junction_count))?Number(drain.junction_count):null,
      WU:Number.isFinite(Number(gama.width_upstream_km))?Number(gama.width_upstream_km):null,
      WL:Number.isFinite(Number(gama.width_lower_km))?Number(gama.width_lower_km):null,
      AU:Number.isFinite(upstreamArea)?upstreamArea:(Number.isFinite(A)&&Number.isFinite(RUA)?A*RUA:null),
    };
  }
  function morphometryState(pointId){
    if(!hssMorphometry.has(pointId)){
      const defaults=extractedMorphometry(pointId);hssMorphometryDefaults.set(pointId,{...defaults});hssMorphometry.set(pointId,{...defaults});
    }
    return hssMorphometry.get(pointId);
  }
  function derivedMorphometry(state){
    const v=k=>Number(state?.[k]);const A=v('A'),Lt=v('Lt'),L1=v('L1'),N=v('N'),N1=v('N1'),WU=v('WU'),WL=v('WL'),AU=v('AU');
    const safe=(x)=>Number.isFinite(x)?x:null;
    const D=Number.isFinite(Lt)&&Number.isFinite(A)&&A>0?Lt/A:null;
    const SF=Number.isFinite(L1)&&Number.isFinite(Lt)&&Lt>0?L1/Lt:null;
    const SN=Number.isFinite(N1)&&Number.isFinite(N)&&N>0?N1/N:null;
    const WF=Number.isFinite(WU)&&Number.isFinite(WL)&&WL>0?WU/WL:null;
    const RUA=Number.isFinite(AU)&&Number.isFinite(A)&&A>0?AU/A:null;
    const SIM=Number.isFinite(WF)&&Number.isFinite(RUA)?WF*RUA:null;
    return {D:safe(D),SF:safe(SF),SN:safe(SN),WF:safe(WF),RUA:safe(RUA),SIM:safe(SIM)};
  }

  function refreshDownloadOption(){
    const count=window.getHssAnalyzedCount();const checkbox=$('downloadHss'),hint=$('downloadHssHint');
    if(checkbox){checkbox.disabled=count===0;if(count===0)checkbox.checked=false;}
    if(hint)hint.textContent=count?`${count} DTA memiliki hasil HSS dan siap disertakan sebagai PDF + Excel.`:'Jalankan Analisis HSS terlebih dahulu untuk mengaktifkan pilihan ini.';
    try{updateDownloadSummary();}catch(_){}
  }
  window.getHssAnalyzedCount=()=>currentPointIds().filter(id=>!hssDirty.has(id)&&hssResults.get(id)?.available_method_count>0).length;
  window.getHssDownloadPayload=()=>{
    const payload={};for(const id of currentPointIds()){const value=hssResults.get(id);if(!hssDirty.has(id)&&value?.available_method_count>0)payload[id]={...value,label:dtaDisplayLabel(id)};}return payload;
  };
  window.invalidateHssForPoint=pointId=>{hssResults.delete(pointId);hssParameters.delete(pointId);hssMorphometry.delete(pointId);hssMorphometryDefaults.delete(pointId);hssTr.delete(pointId);hssMethodSelections.delete(pointId);hssDirty.delete(pointId);refreshDownloadOption();if(currentPointId===pointId&&!$('hssAnalysisModal')?.classList.contains('hidden'))renderHssResults(pointId);};
  window.invalidateAllHss=()=>{hssResults.clear();hssDirty.clear();hssMorphometry.clear();hssMorphometryDefaults.clear();refreshDownloadOption();};
  window.clearHssResults=()=>{hssResults.clear();hssParameters.clear();hssMorphometry.clear();hssMorphometryDefaults.clear();hssTr.clear();hssMethodSelections.clear();hssDirty.clear();refreshDownloadOption();};
  window.refreshHssUiState=()=>{const button=$('hssAnalysisBtn');if(button)button.disabled=currentPointIds().length===0;refreshDownloadOption();};

  function renderDtaSelector(preferredId=null){
    const ids=currentPointIds(),select=$('hssDtaSelect');if(!select)return null;if(!ids.length){select.innerHTML='';currentPointId=null;renderDtaSummary(null);return null;}
    const chosen=(preferredId&&ids.includes(preferredId))?preferredId:(activePointId&&ids.includes(activePointId)?activePointId:ids[0]);currentPointId=chosen;
    select.innerHTML=ids.map(id=>`<option value="${escapeHtml(id)}" ${id===chosen?'selected':''}>${escapeHtml(dtaDisplayLabel(id))}</option>`).join('');
    renderDtaSummary(chosen);
    return chosen;
  }
  function renderDtaSummary(pointId){
    const badge=$('hssDtaStatusBadge');if(!badge)return;
    if(!pointId){badge.className='hss-dta-status-badge hidden';badge.textContent='';return;}
    if(hssDirty.has(pointId)){badge.className='hss-dta-status-badge warn';badge.textContent='⚠ Perlu hitung ulang';return;}
    if(hssResults.get(pointId)?.available_method_count>0){badge.className='hss-dta-status-badge ready';badge.textContent='✓ HSS';return;}
    badge.className='hss-dta-status-badge hidden';badge.textContent='';
  }
  function renderMorphometryControls(pointId){
    const root=$('hssMorphometryControls');if(!root)return;const state=morphometryState(pointId),defaults=hssMorphometryDefaults.get(pointId)||extractedMorphometry(pointId);
    const wasOpen=root.querySelector('.hss-morph-details')?.open===true;
    root.innerHTML=`<details class="hss-morph-details" ${wasOpen?'open':''}><summary><span><i data-lucide="ruler"></i><b>Parameter morfometri</b></span><i class="hss-details-chevron" data-lucide="chevron-down"></i></summary><div class="hss-morph-details-body">
      <div class="hss-method-heading hss-morph-heading"><div><small>Nilai awal berasal dari karakteristik DTA. Perubahan hanya berlaku pada perhitungan HSS ini.</small></div><button id="hssResetMorph" class="text-button hss-reset-with-icon" type="button"><i data-lucide="rotate-ccw"></i>Reset semua</button></div>
      <div class="hss-morph-grid">${MORPH_FIELDS.map(([key,label,unit,min,max,step])=>`<label><span>${escapeHtml(label)}</span><div class="hss-field-row"><div class="hss-input-shell"><input class="hss-morph-input" data-key="${key}" type="number" min="${min}" max="${max}" step="${step}" value="${Number.isFinite(Number(state[key]))?state[key]:''}"><button class="hss-field-reset" data-key="${key}" type="button" aria-label="Reset ${escapeHtml(label)}" title="Reset ke nilai awal"><i data-lucide="rotate-ccw"></i></button></div><b>${escapeHtml(unit)}</b></div></label>`).join('')}</div></div></details>`;
    root.querySelectorAll('.hss-morph-input').forEach(input=>input.addEventListener('input',()=>{const value=Number(input.value);state[input.dataset.key]=Number.isFinite(value)?value:null;refreshGamaDerived(pointId);markDirty(pointId,'Parameter morfometri berubah. Hitung ulang HSS agar hasil, PDF, dan Excel diperbarui.');}));
    root.querySelectorAll('.hss-field-reset').forEach(button=>button.addEventListener('click',()=>{const key=button.dataset.key;state[key]=defaults[key]??null;const input=root.querySelector(`.hss-morph-input[data-key="${key}"]`);if(input)input.value=Number.isFinite(Number(state[key]))?state[key]:'';refreshGamaDerived(pointId);markDirty(pointId,'Parameter morfometri dikembalikan ke nilai awal. Hitung ulang HSS untuk memperbarui hasil.');refreshIcons(root);}));
    $('hssResetMorph')?.addEventListener('click',()=>{hssMorphometry.set(pointId,{...defaults});renderMorphometryControls(pointId);refreshGamaDerived(pointId);markDirty(pointId,'Seluruh parameter morfometri dikembalikan ke hasil ekstraksi. Hitung ulang HSS untuk memperbarui hasil.');refreshIcons(root);});
    refreshIcons(root);
  }
  function renderMorphometryDerived(){/* Parameter turunan ditampilkan khusus sebagai read-only di kartu Gama I. */}
  function gamaDerivedItems(pointId){
    const derived=derivedMorphometry(morphometryState(pointId));
    return [
      ['D','Kerapatan drainase (D)',derived.D,'km/km²',3],
      ['SF','Faktor sumber (SF)',derived.SF,'',3],
      ['SN','Frekuensi sumber (SN)',derived.SN,'',3],
      ['WF','Faktor lebar (WF)',derived.WF,'',3],
      ['RUA','Luas relatif hulu (RUA)',derived.RUA,'',3],
      ['SIM','Faktor simetri (SIM)',derived.SIM,'',3],
    ];
  }
  function gamaDerivedMarkup(pointId){
    return `<div class="hss-gama-derived"><small class="hss-gama-derived-note">Dihitung otomatis dari parameter morfometri HSS.</small><div class="hss-gama-derived-grid">${gamaDerivedItems(pointId).map(([key,label,value,unit,digits])=>`<div class="hss-readonly-param" data-gama-derived="${key}"><span>${escapeHtml(label)}</span><strong>${hssNumber(value,digits)}${unit?` <b>${escapeHtml(unit)}</b>`:''}</strong></div>`).join('')}</div></div>`;
  }
  function refreshGamaDerived(pointId){
    const root=$('hssMethodControls');if(!root)return;
    for(const [key,,value,unit,digits] of gamaDerivedItems(pointId)){
      const target=root.querySelector(`[data-gama-derived="${key}"] strong`);
      if(target)target.innerHTML=`${hssNumber(value,digits)}${unit?` <b>${escapeHtml(unit)}</b>`:''}`;
    }
  }

  function methodGamaHint(){return 'Parameter Gama I dihitung otomatis dari parameter morfometri yang relevan.';}
  function renderMethodControls(pointId){
    const root=$('hssMethodControls');if(!root)return;const state=parameterState(pointId),selected=methodSelectionState(pointId);
    const openMethods=new Set([...root.querySelectorAll('details.hss-method-card[open]')].map(item=>item.dataset.method));
    root.innerHTML=`<div class="hss-method-heading"><div><strong>Metode & koefisien kalibrasi</strong><small>Pilih metode yang dihitung. Buka kartu metode untuk melihat atau mengubah parameternya.</small></div><button id="hssSelectAll" class="text-button" type="button"></button></div><div class="hss-method-grid">${METHOD_DEFS.map((method,index)=>{
      const paramInputs=method.params.length?`<div class="hss-param-grid">${method.params.map(([key,label,defaultValue,min,max,step])=>`<label><span>${escapeHtml(label)}</span><input class="hss-param-input" data-method="${method.id}" data-key="${key}" type="number" min="${min}" max="${max}" step="${step}" value="${state[method.id]?.[key]??defaultValue}"></label>`).join('')}</div>`:(method.id==='gama1'?gamaDerivedMarkup(pointId):`<p class="hss-auto-parameter">${escapeHtml(methodGamaHint())}</p>`);
      const reset=method.params.length?`<button class="hss-reset-method" data-method="${method.id}" type="button"><i data-lucide="rotate-ccw"></i>Reset</button>`:'';
      return `<details class="hss-method-card" data-method="${method.id}" style="--hss-color:${METHOD_COLORS[index]}" ${openMethods.has(method.id)?'open':''}><summary class="hss-method-card-head"><span class="hss-method-toggle"><input class="hss-method-check" type="checkbox" value="${method.id}" ${selected.has(method.id)?'checked':''} aria-label="Pilih ${escapeHtml(method.label)}"><b>${escapeHtml(method.label)}</b></span><i class="hss-details-chevron" data-lucide="chevron-down"></i></summary><div class="hss-method-card-body"><div class="hss-method-meta"><small>${escapeHtml(method.subtitle)}</small>${reset}</div>${paramInputs}</div></details>`;
    }).join('')}</div>`;
    const toggleButton=$('hssSelectAll');
    const updateToggle=()=>{const checks=[...root.querySelectorAll('.hss-method-check')],all=checks.length>0&&checks.every(input=>input.checked);if(toggleButton)toggleButton.textContent=all?'Hapus semua':'Pilih semua';};
    root.querySelectorAll('.hss-method-check').forEach(input=>{input.addEventListener('click',event=>event.stopPropagation());input.addEventListener('change',()=>{if(input.checked)selected.add(input.value);else selected.delete(input.value);updateToggle();});});
    root.querySelectorAll('.hss-method-toggle b').forEach(label=>label.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();const input=label.closest('.hss-method-toggle')?.querySelector('.hss-method-check');if(!input)return;input.checked=!input.checked;input.dispatchEvent(new Event('change',{bubbles:true}));}));
    root.querySelectorAll('.hss-param-input').forEach(input=>input.addEventListener('input',()=>{const method=input.dataset.method,key=input.dataset.key,value=Number(input.value);if(Number.isFinite(value)){parameterState(pointId)[method][key]=value;markDirty(pointId,'Koefisien kalibrasi berubah. Hitung ulang HSS agar hasil, PDF, dan Excel diperbarui.');}}));
    root.querySelectorAll('.hss-reset-method').forEach(button=>button.addEventListener('click',()=>{const method=methodById(button.dataset.method);if(!method)return;const target=parameterState(pointId)[method.id];method.params.forEach(([key,,value])=>target[key]=value);renderMethodControls(pointId);markDirty(pointId,'Koefisien dikembalikan ke nilai awal. Hitung ulang HSS untuk memperbarui hasil.');refreshIcons(root);}));
    toggleButton?.addEventListener('click',()=>{const checks=[...root.querySelectorAll('.hss-method-check')],all=checks.length>0&&checks.every(input=>input.checked);checks.forEach(input=>{input.checked=!all;if(input.checked)selected.add(input.value);else selected.delete(input.value);});updateToggle();});
    updateToggle();refreshIcons(root);
  }

  async function loadPointForHss(pointId){
    const status=$('hssStatus'),needsAnalysis=!pointResult(pointId)?.hydrologic_analysis;let progress=null;
    if(needsAnalysis&&status&&typeof window.startAnalysisProgress==='function')progress=window.startAnalysisProgress(status,'Menghitung karakteristik DTA…');
    else if(status)status.textContent='';
    try{
      if(window.ensureHydrologicAnalysis)await window.ensureHydrologicAnalysis(pointId);
      progress?.complete?.();
      morphometryState(pointId);renderDtaSummary(pointId);renderMorphometryControls(pointId);renderMethodControls(pointId);renderHssResults(pointId);
      if($('hssGlobalTr'))$('hssGlobalTr').value=String(trState(pointId));if(status&&!needsAnalysis)status.textContent=hssDirty.has(pointId)?'Parameter berubah. Hitung ulang HSS untuk memperbarui hasil.':'';
      if(status&&needsAnalysis)setTimeout(()=>{if(status&&!hssDirty.has(pointId))status.textContent='';},220);
    }catch(error){progress?.fail?.();if(status)status.textContent=error?.message||String(error);}
  }
  async function openHssAnalysis(){
    const pointId=renderDtaSelector(activePointId);if(!pointId){showAppToast('Belum ada DTA yang dapat dianalisis.');return;}
    openMapModal($('hssAnalysisModal'));refreshIcons($('hssAnalysisModal'));await loadPointForHss(pointId);
  }

  async function calculateCurrentHss(){
    const pointId=$('hssDtaSelect')?.value||currentPointId;if(!pointId)return;const result=pointResult(pointId);
    if(!result?.hydrologic_analysis){try{await window.ensureHydrologicAnalysis?.(pointId);}catch(error){$('hssStatus').textContent=error?.message||String(error);return;}}
    const methods=[...$('hssMethodControls').querySelectorAll('.hss-method-check:checked')].map(input=>input.value);if(!methods.length){$('hssStatus').textContent='Pilih minimal satu metode HSS.';return;}
    const button=$('runHssBtn'),status=$('hssStatus');button.disabled=true;button.classList.add('is-busy');status.textContent='Menghitung ordinat HSS…';
    try{
      const tr=Number($('hssGlobalTr')?.value);hssTr.set(pointId,Number.isFinite(tr)?tr:1);
      const response=await fetch('/api/hss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({point_id:pointId,label:dtaDisplayLabel(pointId),hydrologic_analysis:result.hydrologic_analysis,methods,parameters:parameterState(pointId),input_overrides:morphometryState(pointId),global_tr_hours:trState(pointId)})});
      const payload=await response.json();if(!response.ok)throw new Error(payload?.detail||'Analisis HSS gagal.');
      hssResults.set(pointId,payload);hssDirty.delete(pointId);currentChartMethod='comparison';renderDtaSelector(pointId);renderHssResults(pointId);refreshDownloadOption();status.textContent=`${payload.available_method_count} dari ${payload.requested_method_count} metode berhasil dihitung.`;showAppToast(`HSS ${dtaDisplayLabel(pointId)} selesai dihitung.`);
    }catch(error){status.textContent=error?.message||String(error);}finally{button.disabled=false;button.classList.remove('is-busy');refreshIcons($('hssAnalysisModal'));}
  }

  function summaryTable(payload){
    const methods=payload.methods||[];return `<div class="hss-summary-wrap"><table class="hss-summary-table"><thead><tr><th>Metode</th><th>Tp</th><th>Qp</th><th>Tb</th><th>Limpasan</th><th>Error volume</th></tr></thead><tbody>${methods.map(method=>{if(!method.available)return `<tr class="hss-unavailable"><th>${escapeHtml(method.label)}</th><td colspan="5">${escapeHtml((method.warnings||[]).join(' ')||'Belum dapat dihitung.')}</td></tr>`;const error=Number(method.volume_error_pct),cls=Math.abs(error)<=5?'ok':Math.abs(error)<=15?'warn':'alert';return `<tr><th>${escapeHtml(method.label)}</th><td>${hssNumber(method.Tp_hours,2)} jam</td><td>${hssNumber(method.Qp_m3s,3)} m³/s</td><td>${hssNumber(method.Tb_hours,2)} jam</td><td>${hssNumber(method.equivalent_runoff_mm,3)} mm</td><td><span class="hss-volume-badge ${cls}">${error>=0?'+':''}${hssNumber(error,2)}%</span></td></tr>`;}).join('')}</tbody></table></div>`;
  }
  function renderHssDirtyState(pointId,message=null){if($('hssDtaSelect')&&currentPointIds().includes(pointId))renderDtaSelector(pointId);const status=$('hssStatus');if(status&&hssDirty.has(pointId))status.textContent=message||'Parameter berubah. Hitung ulang HSS agar hasil, PDF, dan Excel diperbarui.';const banner=$('hssDirtyBanner');if(banner)banner.classList.toggle('hidden',!hssDirty.has(pointId));}

  function renderHssResults(pointId){
    const root=$('hssResults');if(!root)return;const payload=hssResults.get(pointId);if(chartInstance){chartInstance.destroy();chartInstance=null;}
    if(!payload){root.innerHTML='<div class="hss-empty-result"><i data-lucide="activity"></i><div><strong>HSS belum dihitung untuk DTA ini.</strong><span>Atur parameter dan koefisien, lalu tekan Hitung HSS.</span></div></div>';refreshIcons(root);return;}
    const available=(payload.methods||[]).filter(method=>method.available);
    root.innerHTML=`<div id="hssDirtyBanner" class="hss-dirty-banner ${hssDirty.has(pointId)?'':'hidden'}"><i data-lucide="triangle-alert"></i><span>Parameter telah berubah. Grafik di bawah masih hasil sebelumnya dan tidak akan diekspor sebelum dihitung ulang.</span></div>
      <div class="hss-result-head"><div><strong>Hasil HSS — ${escapeHtml(dtaDisplayLabel(pointId))}</strong><small>${available.length} metode tersedia · Tr ${hssNumber(payload.global_tr_hours??1,2)} jam · hujan efektif satuan 1 mm</small></div><label class="hss-normalized-toggle"><input id="hssNormalizedToggle" type="checkbox"><span>Grafik ternormalisasi 1 mm</span></label></div>${summaryTable(payload)}
      <div class="hss-chart-section"><div class="hss-chart-tabs"><button class="hss-chart-tab ${currentChartMethod==='comparison'?'active':''}" data-method="comparison" type="button">Perbandingan</button>${available.map(method=>`<button class="hss-chart-tab ${currentChartMethod===method.method?'active':''}" data-method="${method.method}" type="button">${escapeHtml(method.label)}</button>`).join('')}</div>
      <div class="hss-chart-toolbar"><span>Scroll untuk zoom horizontal · geser grafik untuk pan horizontal · arahkan kursor untuk melihat nilai</span><button id="hssResetZoom" class="text-button hss-reset-with-icon" type="button"><i data-lucide="scan"></i>Reset Zoom</button></div><div class="hss-chart-canvas"><canvas id="hssChart"></canvas></div><div id="hssChartDetails" class="hss-chart-details"></div></div>`;
    root.querySelectorAll('.hss-chart-tab').forEach(button=>button.addEventListener('click',()=>{currentChartMethod=button.dataset.method;root.querySelectorAll('.hss-chart-tab').forEach(tab=>tab.classList.toggle('active',tab===button));renderChart(payload,currentChartMethod,$('hssNormalizedToggle')?.checked===true);}));
    $('hssNormalizedToggle')?.addEventListener('change',event=>renderChart(payload,currentChartMethod,event.currentTarget.checked));
    $('hssResetZoom')?.addEventListener('click',()=>chartInstance?.resetZoom?.());
    if(currentChartMethod!=='comparison'&&!available.some(method=>method.method===currentChartMethod))currentChartMethod='comparison';renderChart(payload,currentChartMethod,false);refreshIcons(root);
  }
  function chartSeries(payload,methodId,normalized){
    const methods=(payload.methods||[]).filter(method=>method.available&&(methodId==='comparison'||method.method===methodId));return methods.map(method=>({method,label:method.label,color:METHOD_COLORS[Math.max(0,METHOD_DEFS.findIndex(item=>item.id===method.method))],points:(method.ordinates||[]).map(row=>({x:Number(row.time_hours),y:Number(normalized?row.normalized_discharge_m3s:row.discharge_m3s)})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.y>=0)}));
  }
  function cssColor(variable,fallback){try{return getComputedStyle(document.documentElement).getPropertyValue(variable).trim()||fallback;}catch(_){return fallback;}}
  function renderChart(payload,methodId='comparison',normalized=false){
    const canvas=$('hssChart'),details=$('hssChartDetails');if(!canvas)return;const series=chartSeries(payload,methodId,normalized);if(chartInstance){chartInstance.destroy();chartInstance=null;}
    if(!series.length){canvas.parentElement.innerHTML='<div class="hss-empty-chart">Kurva HSS belum tersedia.</div>';if(details)details.innerHTML='';return;}
    if(!window.Chart){canvas.parentElement.innerHTML='<div class="hss-empty-chart">Chart.js belum termuat. Muat ulang halaman untuk menampilkan grafik interaktif.</div>';return;}
    chartInstance=new Chart(canvas,{type:'line',data:{datasets:series.map(item=>({label:item.label,data:item.points,borderColor:item.color,backgroundColor:item.color,borderWidth:2.2,pointRadius:0,pointHoverRadius:4,pointHitRadius:9,tension:.12,fill:false}))},options:{responsive:true,maintainAspectRatio:false,animation:{duration:180},normalized:true,interaction:{mode:'nearest',intersect:false,axis:'xy'},plugins:{legend:{display:methodId==='comparison',position:'bottom',labels:{usePointStyle:true,boxWidth:8,boxHeight:8,font:{size:12}}},tooltip:{enabled:true,callbacks:{title:(items)=>items.length?`Waktu: ${hssNumber(items[0].parsed.x,3)} jam`:'',label:(ctx)=>`${ctx.dataset.label}: ${hssNumber(ctx.parsed.y,4)} m³/s`}},zoom:{limits:{x:{min:0,minRange:.05}},pan:{enabled:true,mode:'x'},zoom:{wheel:{enabled:true,speed:.08},pinch:{enabled:true},drag:{enabled:false},mode:'x'}}},scales:{x:{type:'linear',title:{display:true,text:'Waktu (jam)',font:{weight:'600'}},min:0,grid:{color:cssColor('--border-color','#e0e5ed')}},y:{type:'linear',title:{display:true,text:'Debit (m³/s)',font:{weight:'600'}},beginAtZero:true,grid:{color:cssColor('--border-color','#e0e5ed')}}}}});
    if(details){if(methodId==='comparison')details.innerHTML='<span>Tooltip menampilkan waktu dan debit setiap kurva. Gunakan tab metode untuk melihat parameter individual.</span>';else{const method=series[0].method,paramText=Object.entries(method.parameters||{}).map(([key,value])=>`${key}=${hssNumber(value,3)}`).join(' · '),tpLabel=method.method==='gama1'?'TR = Tp':'Tp';details.innerHTML=`<div><b>${tpLabel}</b><span>${hssNumber(method.Tp_hours,3)} jam</span></div><div><b>Qp</b><span>${hssNumber(normalized?method.Qp_m3s*method.normalization_factor:method.Qp_m3s,4)} m³/s</span></div><div><b>Tb</b><span>${hssNumber(method.Tb_hours,3)} jam</span></div><div><b>Volume</b><span>${normalized?'1,000 mm':`${hssNumber(method.equivalent_runoff_mm,4)} mm`}</span></div>${paramText?`<p>${escapeHtml(paramText)}</p>`:''}`;}}
  }

  $('hssAnalysisBtn')?.addEventListener('click',openHssAnalysis);
  $('closeHssAnalysisModal')?.addEventListener('click',()=>{if(chartInstance){chartInstance.destroy();chartInstance=null;}closeMapModal($('hssAnalysisModal'));});
  $('hssDtaSelect')?.addEventListener('change',async event=>{currentPointId=event.currentTarget.value;currentChartMethod='comparison';await loadPointForHss(currentPointId);refreshIcons($('hssAnalysisModal'));});
  $('hssGlobalTr')?.addEventListener('input',event=>{if(!currentPointId)return;const value=Number(event.currentTarget.value);if(Number.isFinite(value)){hssTr.set(currentPointId,value);markDirty(currentPointId,'Tr berubah. Hitung ulang HSS agar metode yang memerlukan durasi hujan efektif menggunakan nilai terbaru.');}});
  $('runHssBtn')?.addEventListener('click',calculateCurrentHss);
  $('hssAnalysisModal')?.addEventListener('click',event=>{if(event.target.id==='hssAnalysisModal'){if(chartInstance){chartInstance.destroy();chartInstance=null;}closeMapModal(event.currentTarget);}});
  window.refreshHssUiState();
})();
