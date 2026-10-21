(() => {
  'use strict';
  const selected = new Set(), mapping = new Map();
  let workbook = null, sourceFile = '', result = null, resultRecipe = null, previousGeometry = '', revision = 0, uploadRevision = 0, reliabilityChart = null;
  let running = false, mockSimulated = false;
  const mockValues=new Map();
  let mockGis=null, mockLoading=false, mockLoadRevision=0;
  const mockKeys=['smc_multiplier','infiltration','k30'];
  const el = id => document.getElementById(id);
  const escape = value => escapeHtml(String(value ?? ''));
  const available = () => points.filter(p => pointResult(p.point_id)?.dta_geojson);
  const name = id => String(pointName(id) || id);
  const groups = () => [...document.querySelectorAll('.hydro-group:checked')].map(input => input.value);
  const selectedModel = () => {
    const input = document.querySelector('input[name="hydrologyModel"]:checked');
    return input ? input.value : 'hydromodar';
  };
  function showSelectedModel() {
    document.querySelectorAll('[data-hydro-panel]').forEach(panel => panel.classList.toggle('hidden', panel.dataset.hydroPanel !== selectedModel()));
    document.querySelector('[data-hydro-climate-years]').hidden = selectedModel() === 'hydromodar';
    el('hydroModelPicker').classList.add('hidden');
    el('hydroModelSetup').classList.remove('hidden');
    invalidate(); renderDonors();
  }
  function showModelPicker() {
    el('hydroModelSetup').classList.add('hidden');
    document.querySelectorAll('input[name="hydrologyModel"]').forEach(input => { input.checked = false; });
    el('hydroModelPicker').classList.remove('hidden');
  }
  const fingerprint = () => JSON.stringify({points: available().map(p => [p.point_id,p.lon,p.lat,p.label,p.river_name,pointResult(p.point_id).dta_geojson]),snap:snapRadiusEl.value,boundary:boundaryMatchEl.value});
  const number = value => {
    if(value===null || value===undefined) return 'n.a.';
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 'n.a.';
    return window.formatDisplayNumber?.(numeric) ?? numeric.toLocaleString('id-ID');
  };
  function invalidate(message = 'Input berubah. Jalankan Simulasi untuk memperbarui hasil.', keepMockSimulation = false) {
    revision++;
    if (!keepMockSimulation) { mockSimulated=false; el('hydroMockMode').value='gis'; }
    if (result) el('hydroStatus').textContent = message;
    result = null; resultRecipe = null;
    el('hydroResults').replaceChildren();
    downloadState();
  }
  function downloadState() {
    const ready = Boolean(result && previousGeometry === fingerprint());
    const box = el('downloadHydroModel');
    box.disabled = !ready;
    if (!ready) box.checked = false;
    el('downloadHydroModelHint').textContent = ready ? `${result.results.length} DTA siap. Satu workbook model dengan satu sheet per DTA target.` : 'Jalankan simulasi terlebih dahulu. Hasil lama tidak dapat diunduh setelah input berubah.';
  }
  function sheetFor(id) {
    if (!workbook) return null;
    return selected.size === 1 ? workbook.sheets[0] : workbook.sheets.find(s => s.name === mapping.get(id));
  }
  function commonYears() {
    const donors = [...selected].map(sheetFor);
    if (!donors.length || donors.some(s => !s || s.error)) return [];
    return donors[0].records.map(r => r.year).filter(y => donors.every(s => s.records.some(r => r.year === y))).sort((a,b)=>a-b);
  }
  const yearRanges = years => years.reduce((ranges, year) => {
    const current = ranges.at(-1);
    if (current && year === current[1] + 1) current[1] = year;
    else ranges.push([year, year]);
    return ranges;
  }, []).map(([start, end]) => start === end ? start : `${start}–${end}`).join(', ');
  function updateInfo() {
    const dtaCount = available().length;
    const enoughDtas = dtaCount >= (selectedModel()==='hydromodar'?2:1);
    el('hydroModelBtn').disabled = dtaCount === 0;
    el('hydroModelBtn').removeAttribute('title');
    el('runHydroModel').disabled = running || mockLoading || !enoughDtas;
    el('hydroLoadGisParameters').disabled=running||mockLoading||!available().length;
    el('hydroMockMode').disabled=!mockSimulated||running||mockLoading;
    el('hydroMockCalibrationInfo').textContent=mockSimulated
      ? 'Kalibrasi siap. Mode otomatis memakai debit pengamatan.'
      : 'Jalankan simulasi awal untuk membuka kalibrasi.';
    el('hydroMockBounds').disabled=!mockSimulated||running||mockLoading||el('hydroMockMode').value!=='auto';
    el('hydroMockParameterValues').querySelectorAll('input').forEach(input=>input.disabled=!mockSimulated||running||mockLoading||el('hydroMockMode').value==='gis');
    el('runHydroModel').textContent=selectedModel()==='mock'&&mockSimulated&&el('hydroMockMode').value!=='gis' ? 'Jalankan Kalibrasi' : 'Jalankan Simulasi';
    const targets = available().filter(p => selectedModel()!=='hydromodar' || !selected.has(p.point_id));
    el('hydroTargets').textContent = `${selected.size} referensi; ${targets.length} target: ${targets.map(p => name(p.point_id)).join(', ') || 'belum ada'}.`;
    const years = commonYears();
    el('hydroPeriod').textContent = years.length ? `Irisan ${years.length} tahun: ${yearRanges(years)} (${years.length * 24} periode).` : 'Belum ada irisan tahun yang valid pada sheet referensi terpilih.';
    el('hydroMethodInfo').textContent = selected.size > 1 ? `Beberapa referensi: transfer DAR dengan ${groups().length ? 'bobot kemiripan per DTA target' : 'bobot sama'}. Referensi bersarang tetap diterima dan diberi keterangan.` : 'Satu referensi: DAR langsung. Parameter kemiripan hanya memeriksa kesesuaian; bobot tetap 1.';
    el('hydroSoilDepth').disabled = !groups().includes('soil');
    const mock=selectedModel()==='mock', start=Number(el('hydroStartYear').value), end=Number(el('hydroEndYear').value), warm=Number(el('hydroWarmupYears').value);
    el('hydroWarmupInfo').hidden=!mock;
    el('hydroWarmupInfo').textContent=Number.isInteger(start)&&Number.isInteger(end)&&Number.isInteger(warm)&&warm>=0&&warm<=100&&start+warm<=end
      ? `${warm ? `Pemanasan ${start}–${start+warm-1}. ` : ''}Keluaran ${start+warm}–${end}.`
      : 'Rentang iklim harus menyisakan periode keluaran.';
  }
  function renderMockValues() {
    if(!mockGis){el('hydroMockParameterValues').replaceChildren();return;}
    el('hydroMockParameterValues').innerHTML=`<table><thead><tr><th>DTA</th><th>Pengali SMC GIS</th><th>Infiltrasi i</th><th>Resesi k30 (30 hari)</th></tr></thead><tbody>${mockGis.points.map(p=>{
      const values=mockValues.get(p.point_id), gis=[p.soil_parameters.smc_mm,p.soil_parameters.infiltration,p.recession_parameters.k30];
      return `<tr><th scope="row">${escape(p.label)}</th>${mockKeys.map((key,j)=>`<td><input type="number" step="any" data-mock-point="${escape(p.point_id)}" data-mock-value="${key}" aria-label="${escape(key)} ${escape(p.label)}" value="${values[key]??''}"><small>GIS: ${number(gis[j])}${j===0?' mm':''}</small></td>`).join('')}</tr>`;
    }).join('')}</tbody></table>`;
    el('hydroMockParameterValues').querySelectorAll('input').forEach(input=>input.addEventListener('input',()=>{
      mockValues.get(input.dataset.mockPoint)[input.dataset.mockValue]=input.value===''?null:Number(input.value);
      invalidate(undefined,true);updateInfo();
    }));
    updateInfo();
  }
  function mockSettings() {
    const mode=mockSimulated?el('hydroMockMode').value:'gis', overrides={};
    if(mode==='auto'&&!selected.size) throw new Error('Pasangkan debit pengamatan ke minimal satu DTA untuk kalibrasi otomatis.');
    if(mode!=='gis') for(const [id,values] of mockValues){
      for(const key of mockKeys){
        const v=values[key],valid=Number.isFinite(v)&&(key==='smc_multiplier'?v>0:key==='infiltration'?v>=0&&v<=1:v>0&&v<1);
        if(!valid) throw new Error(`${name(id)}: isi ${key} yang valid; periksa prior GIS atau masukkan nilai manual.`);
      }
      overrides[id]={...values};
    }
    const bounds={},fit=[];
    for(const key of mockKeys){
      const loInput=document.querySelector(`[data-mock-lower="${key}"]`),hiInput=document.querySelector(`[data-mock-upper="${key}"]`);
      const lo=Number(loInput.value),hi=Number(hiInput.value);
      if(mode==='auto'&&(!loInput.value.trim()||!hiInput.value.trim()||!Number.isFinite(lo)||!Number.isFinite(hi)||lo>hi||
        (key==='smc_multiplier'?lo<=0:key==='infiltration'?lo<0||hi>1:lo<=0||hi>=1))) throw new Error(`Rentang ${key} tidak valid.`);
      if(mode==='auto') bounds[key]=[lo,hi];
      if(document.querySelector(`[data-mock-fit="${key}"]`).checked) fit.push(key);
    }
    return {mock_mode:mode,mock_parameters:overrides,mock_bounds:bounds,mock_fit_parameters:fit};
  }
  function renderDonors() {
    const count = selected.size;
    el('hydroDonors').innerHTML = available().map(p => {
      const id = p.point_id, active = selected.has(id);
      const sheet = sheetFor(id);
      const options = (workbook?.sheets || []).map(s => `<option value="${escape(s.name)}" ${mapping.get(id) === s.name ? 'selected' : ''}>${escape(s.name)}${s.error ? ' — tidak valid' : ''}</option>`).join('');
      return `<div class="hydro-donor-row"><label class="hydro-donor-choice"><input type="checkbox" data-donor="${escape(id)}" ${active ? 'checked' : ''}>${escape(name(id))}</label><div>${active ? count === 1 ? `<span>Sheet pertama: ${escape(sheet?.name || 'belum diunggah')}</span>` : `<label>Sheet debit<select data-sheet="${escape(id)}" aria-label="Sheet debit ${escape(name(id))}"><option value="">Pilih sheet</option>${options}</select></label>` : '<small>Target model</small>'}${active && sheet?.error ? `<p role="alert">${escape(sheet.error)}</p>` : ''}</div></div>`;
    }).join('');
    el('hydroDonors').querySelectorAll('[data-donor]').forEach(input => input.addEventListener('change', () => {
      if (input.checked) selected.add(input.dataset.donor); else selected.delete(input.dataset.donor);
      invalidate(); renderDonors();
    }));
    el('hydroDonors').querySelectorAll('[data-sheet]').forEach(input => input.addEventListener('change', () => {
      mapping.set(input.dataset.sheet, input.value); invalidate(); updateInfo();
    }));
    updateInfo();
  }
  function recipe() {
    const model=selectedModel()==='ml'?el('hydroMlAlgorithm').value:selectedModel();
    const dar=model==='hydromodar';
    const start=Number(el('hydroStartYear').value),end=Number(el('hydroEndYear').value),warm=Number(el('hydroWarmupYears').value);
    if(!dar && (!Number.isInteger(start)||!Number.isInteger(end)||start<1990||end>2100||start>end)) throw new Error('Rentang tahun iklim tidak valid.');
    if(model==='mock' && (!el('hydroWarmupYears').value.trim()||!Number.isInteger(warm)||warm<0||warm>100||start+warm>end)) throw new Error('Pemanasan harus 0–100 tahun bulat dan menyisakan minimal satu tahun keluaran.');
    if ((dar || model!=='mock') && (!workbook || !selected.size)) throw new Error('Unggah Excel dan pilih minimal satu DTA referensi.');
    if (dar && selected.size >= available().length) throw new Error('Sisakan minimal satu DTA target.');
    const donors = [...selected].map(id => {
      const sheet = sheetFor(id);
      if (!sheet) throw new Error(`Pilih sheet debit untuk ${name(id)}.`);
      if (sheet.error) throw new Error(`${name(id)} / ${sheet.name}: ${sheet.error}`);
      if(dar && sheet.records.some(r=>r.values.some(v=>v===null))) throw new Error('HydroMODAR memerlukan tahun debit lengkap. FJ Mock dan ML menerima periode kosong.');
      return {point_id:id, sheet:sheet.name, records:sheet.records};
    });
    if (new Set(donors.map(d=>d.sheet)).size !== donors.length) throw new Error('Satu sheet hanya boleh dipasangkan ke satu DTA referensi.');
    if (dar && !commonYears().length) throw new Error('Tidak ada irisan tahun seluruh referensi.');
    const b = Number(el('hydroExponent').value);
    if (!Number.isFinite(b) || b <= 0 || b > 3) throw new Error('Eksponen luas b harus > 0 dan ≤ 3.');
    return {points:available().map(({point_id,lon,lat,source,label,river_name})=>({point_id,lon,lat,source,label,river_name})),
      model, start_year:Number(el('hydroStartYear').value),end_year:Number(el('hydroEndYear').value),
      warmup_years:model==='mock'?warm:0,
      ...(model==='mock'?mockSettings():{}),
      donors, groups:dar?groups():[], b, soil_depth:Number(el('hydroSoilDepth').value),source_file:sourceFile,
      source_notes:el('hydroSourceNotes').value, snap_radius_m:Number(snapRadiusEl.value), boundary_match_m:Number(boundaryMatchEl.value)};
  }
  function showResult() {
    if (!result) return;
    el('hydroResults').innerHTML = `<section class="hydro-model-result"><h3>Hasil model</h3><label>DTA target<select id="hydroResultDta">${result.results.map(r=>`<option value="${escape(r.point_id)}">${escape(r.label)}</option>`).join('')}</select></label><div id="hydroResultDetail"></div></section>`;
    el('hydroResultDta').addEventListener('change', detail);
    detail();
  }
  function detail() {
    const r = result.results.find(r=>r.point_id === el('hydroResultDta').value), s = r.statistics;
    const qs = Object.entries(s.quantiles);
    el('hydroResultDetail').innerHTML = `<p>${escape(result.method)}; luas ${number(r.area_km2)} km²; ${s.count} periode. Debit dalam m³/det.</p>
      <div class="hydro-model-table hydro-quantile-table"><table><thead><tr>${qs.map(([k])=>`<th>${k}</th>`).join('')}</tr></thead><tbody><tr>${qs.map(([,v])=>`<td>${number(v)}</td>`).join('')}</tr></tbody></table></div>
      <p>Minimum ${number(s.min)}; maksimum ${number(s.max)}; rerata ${number(s.mean)}; median ${number(s.median)}; simpangan baku sampel ${number(s.std)}; CV ${number(s.cv)}; jumlah nol ${s.zero_count}.</p>
      ${renderReliabilityChart(r)}
      ${r.donors.length ? `<div class="hydro-model-table"><table><thead><tr><th>Referensi</th><th>Sheet</th><th>Bobot</th><th>Jarak kemiripan</th></tr></thead><tbody>${r.donors.map(d=>`<tr><td>${escape(d.label)}</td><td>${escape(d.sheet)}</td><td>${number(d.weight*100)}%</td><td>${number(d.distance)}</td></tr>`).join('')}</tbody></table></div>` : ''}
      ${renderRunoffAudit(r)}
      ${r.observation_comparison?`<h4>Perbandingan debit pengamatan</h4><p>${escape(r.comparison_note)} n=${r.observation_comparison.count}; NSE ${number(r.observation_comparison.nse)}; KGE ${number(r.observation_comparison.kge)}; RMSE ${number(r.observation_comparison.rmse)} m³/det; PBIAS ${number(r.observation_comparison.pbias_pct)}%.</p>`:''}
      ${renderHydrogeologyContext(r)}
      ${renderRainfall(r)}
      <div class="hydro-model-table hydro-semimonthly-table"><table><caption>Debit hasil model tengah bulanan (m³/det)</caption><thead><tr><th scope="col" rowspan="2">Tahun</th>${['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Ags','Sep','Okt','Nov','Des'].map(month=>`<th scope="colgroup" colspan="2">${month}</th>`).join('')}</tr><tr>${Array.from({length:12},()=>'<th scope="col">I</th><th scope="col">II</th>').join('')}</tr></thead><tbody>${r.records.map(row=>`<tr><th scope="row">${row.year}</th>${row.values.map(q=>`<td>${number(q)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <p class="hydro-model-note">${escape(result.statistic_convention)}. ${escape(result.uncertainty_note)}</p>
      ${r.warnings.length ? `<ul>${r.warnings.map(w=>`<li>${escape(w)}</li>`).join('')}</ul>` : ''}
      ${!result.model && result.validation.length ? `<h4>Validasi bergiliran referensi</h4><div class="hydro-model-table"><table><thead><tr><th>DTA uji</th><th>APE Q50 model</th><th>APE Q50 luas saja</th><th>RMSE (m³/det)</th><th>Bias (m³/det)</th></tr></thead><tbody>${result.validation.map(v=>`<tr><td>${escape(v.label)}</td><td>${number(v.ape_q50_pct)}%</td><td>${number(v.baseline_ape_q50_pct)}%</td><td>${number(v.rmse)}</td><td>${number(v.bias)}</td></tr>`).join('')}</tbody></table></div><p class="hydro-model-note">${escape(result.validation_note)}</p>` : ''}`;
    bindReliabilityChart(r);
  }
  function renderRunoffAudit(target) {
    if(!result.model) return '';
    const soil=target.soil_parameters, p=target.model_parameters, c=target.climate;
    return `<h4>Parameter GIS &amp; model</h4><p>SMC akar 1 m: ${number(soil.smc_mm)} mm; Ksat profil: ${number(soil.ksat_mm_h)} mm/jam; infiltrasi GIS: ${number(soil.infiltration)}.</p><p>${escape(p.status)}</p>${result.model==='mock'?`<p>Parameter terpakai: SMC ${number(p.smc_mm)} mm; infiltrasi ${number(p.infiltration)}; k30 ${number(p.k30)} (GIS ${number(p.gis_prior?.k30)}).</p>${p.clipped_initial_parameters?.length?`<p>Nilai awal disesuaikan ke rentang otomatis: ${escape(p.clipped_initial_parameters.join(', '))}.</p>`:''}`:''}${result.model==='mock'?`<p>Pemanasan ${p.warmup_years} tahun; keluaran mulai ${escape(c.output_start)}. ${escape(p.spinup)}</p>`:''}<p>${escape(soil.status)} ${escape(c.method)}</p><p>Periode iklim terakhir: ${escape(c.last_complete_period)}. ${p.max_balance_error_mm!==undefined?`Galat neraca air maksimum: ${number(p.max_balance_error_mm)} mm.`:''}</p><details><summary>Rincian parameter dan sumber</summary><pre>${escape(JSON.stringify({soil,model:p,et0:c.et0},null,2))}</pre></details>${result.validation.length?`<h4>Validasi independen</h4><div class="hydro-model-table"><table><thead><tr><th>DTA</th><th>Skema</th><th>n</th><th>RMSE m³/det</th><th>NSE</th><th>KGE</th><th>PBIAS %</th></tr></thead><tbody>${result.validation.map(v=>`<tr><td>${escape(v.label)}</td><td>${escape(v.scheme)}</td><td>${v.count}</td><td>${number(v.rmse)}</td><td>${number(v.nse)}</td><td>${number(v.kge)}</td><td>${number(v.pbias_pct)}</td></tr>`).join('')}</tbody></table></div><p>${escape(result.validation_note)}</p>`:'<p>Belum ada validasi independen yang memadai.</p>'}`;
  }
  function renderRainfall(target) {
    if (!target.rainfall) return '';
    const rain = target.rainfall;
    return `<h4>Hujan tengah bulanan</h4><p class="hydro-model-note">${escape(result.rainfall_convention)} ${escape(rain.spatial_method)}</p><p>Sumber: ${escape(rain.source)}; tahun ${escape(yearRanges(rain.years))}.</p><div class="hydro-model-table"><table><thead><tr><th>DTA</th><th>Peran</th><th>Rerata hujan tahunan (mm)</th><th>Cakupan valid minimum</th></tr></thead><tbody>${[target,...target.donors].map((p,i)=>`<tr><td>${escape(p.label)}</td><td>${i===0?'Target':'Referensi'}</td><td>${number(p.rainfall?.mean_annual_mm)}</td><td>${number(p.rainfall?.coverage_min*100)}%</td></tr>`).join('')}</tbody></table></div><details><summary>Hujan rerata areal target (mm/tengah bulan)</summary><div class="hydro-model-table"><table><thead><tr><th>Tahun</th>${['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Ags','Sep','Okt','Nov','Des'].flatMap(m=>['I','II'].map(h=>`<th>${m} ${h}</th>`)).join('')}</tr></thead><tbody>${rain.records.map(r=>`<tr><th>${r.year}</th>${r.values.map(v=>`<td>${number(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
  }
  function renderHydrogeologyContext(target) {
    const describe = (point, key) => {
      const context = point.hydrogeology_context?.[key];
      if (!context?.available) return 'Data tidak tersedia';
      const classes = Object.entries(context.classes || {}).map(([label, fraction])=>`${escape(label)}: ${number(fraction*100)}%`).join('; ');
      return `${classes || 'Tidak ada irisan terpetakan'}<br><small>Cakupan ${number(context.coverage*100)}% luas DTA</small>`;
    };
    return `<h4>Konteks hidrogeologi</h4><p class="hydro-model-note">${result.model==='mock'?'Litologi dan produktivitas/ketersediaan membentuk prior resesi GIS heuristik; CAT membantu kemiripan regional referensi.':'CAT dan litologi digunakan untuk pemeriksaan kesesuaian, tanpa menambah bobot atau debit.'} Persentase dihitung terhadap seluruh luas DTA. Kesamaan CAT belum membuktikan konektivitas air tanah.</p><div class="hydro-model-table"><table><thead><tr><th>DTA</th><th>Peran</th><th>CAT</th><th>Litologi</th></tr></thead><tbody>${[target,...target.donors].map((point,index)=>`<tr><td>${escape(point.label)}</td><td>${index===0?'Target':'Referensi'}</td><td>${describe(point,'cat')}</td><td>${describe(point,'lithology')}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function renderReliabilityChart(r) {
    return `<section class="hydro-reliability hss-chart-section"><div class="hydro-reliability-head"><div><strong>Debit andalan tengah bulanan</strong><small>Persentil tiap periode dari seluruh tahun simulasi.</small></div></div><div class="hss-chart-toolbar"><span>Scroll untuk zoom horizontal · geser grafik untuk pan · arahkan kursor untuk melihat nilai</span><button id="hydroResetZoom" class="text-button hss-reset-with-icon" type="button"><i data-lucide="scan"></i>Reset Zoom</button></div><div class="hss-chart-canvas hydro-chart-canvas"><canvas id="hydroReliabilityChart"></canvas></div><div id="hydroChartDetails" class="hss-chart-details"></div></section>`;
  }
  function bindReliabilityChart(r) {
    const canvas = el('hydroReliabilityChart'), details=el('hydroChartDetails');
    if (!canvas) return;
    const labels = ['Jan I','Jan II','Feb I','Feb II','Mar I','Mar II','Apr I','Apr II','Mei I','Mei II','Jun I','Jun II','Jul I','Jul II','Ags I','Ags II','Sep I','Sep II','Okt I','Okt II','Nov I','Nov II','Des I','Des II'];
    const style=getComputedStyle(document.documentElement),border=style.getPropertyValue('--border-color').trim()||'#e0e5ed';
    const probabilities=['Q10','Q20','Q25','Q30','Q40','Q50','Q60','Q70','Q80','Q90','Q95'];
    const active=new Set(['Q90','Q80','Q50','Q30']);
    const colors=['#223468','#D97706','#16836B','#7C4D9A','#B64E58','#2678B2','#697B2B','#223468','#D97706','#16836B','#7C4D9A'];
    const datasets=probabilities.map((key,index)=>({label:key,data:r.period_statistics.map(row=>row.quantiles[key]),borderColor:colors[index],backgroundColor:colors[index],borderWidth:2.2,pointRadius:0,pointHoverRadius:4,pointHitRadius:9,tension:.12,spanGaps:false,hidden:!active.has(key)})).filter(dataset=>dataset.data.some(value=>value!==null));
    reliabilityChart?.destroy(); reliabilityChart=null;
    if (!datasets.length) { canvas.parentElement.innerHTML='<div class="hss-empty-chart">Debit andalan belum tersedia untuk jumlah tahun simulasi ini.</div>'; if(details)details.textContent=''; return; }
    if (!window.Chart) { canvas.parentElement.innerHTML='<div class="hss-empty-chart">Menyiapkan grafik interaktif…</div>'; return; }
    reliabilityChart=new Chart(canvas,{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,animation:{duration:180},interaction:{mode:'index',intersect:false},plugins:{legend:{display:true,position:'bottom',labels:{usePointStyle:true,boxWidth:8,boxHeight:8,font:{size:12}}},tooltip:{enabled:true,callbacks:{label:ctx=>`${ctx.dataset.label}: ${number(ctx.parsed.y)} m³/det`}},zoom:{limits:{x:{min:0,max:23,minRange:2}},pan:{enabled:true,mode:'x'},zoom:{wheel:{enabled:true,speed:.08},pinch:{enabled:true},drag:{enabled:false},mode:'x'}}},scales:{x:{title:{display:true,text:'Periode tengah bulanan',font:{weight:'600'}},ticks:{autoSkip:true,maxTicksLimit:12},grid:{color:border}},y:{title:{display:true,text:'Debit (m³/det)',font:{weight:'600'}},beginAtZero:true,grid:{color:border}}}}});
    if(details)details.textContent='Klik label legenda untuk menampilkan atau menyembunyikan kurva. Scroll untuk zoom, geser grafik untuk pan, dan arahkan kursor untuk melihat nilai.';
    el('hydroResetZoom')?.addEventListener('click',()=>reliabilityChart?.resetZoom?.());
  }
  window.refreshHydroModelUiState = () => {
    if (!el('hydroModelBtn')) return;
    const current = fingerprint();
    if (previousGeometry && current !== previousGeometry) {
      invalidate('DTA atau pengaturan delineasi berubah. Jalankan ulang simulasi.');
      mockLoadRevision++;mockGis=null;mockValues.clear();renderMockValues();
      el('hydroMockParameterStatus').textContent='DTA berubah. Muat ulang parameter GIS.';
    }
    previousGeometry = current;
    const valid = new Set(available().map(p=>p.point_id));
    for (const id of selected) if (!valid.has(id)) selected.delete(id);
    updateInfo();
    if (!el('hydroModelModal').classList.contains('hidden')) renderDonors();
    downloadState();
  };
  window.getHydroModelDownloadPayload = () => {
    if (!result || previousGeometry !== fingerprint()) throw new Error('Hasil model perlu dihitung ulang.');
    return resultRecipe;
  };
  window.getHydroModelCount = () => result && previousGeometry === fingerprint() ? result.results.length : 0;
  window.refreshHydroModelDecimalDisplay = () => { if (result) detail(); renderObservedStatistics(); };
  el('hydroModelBtn').addEventListener('click', () => {window.refreshHydroModelUiState();showModelPicker();openMapModal(el('hydroModelModal'));});
  document.querySelectorAll('input[name="hydrologyModel"]').forEach(input => input.addEventListener('change', showSelectedModel));
  el('chooseAnotherHydroModel').addEventListener('click',showModelPicker);
  el('closeHydroModel').addEventListener('click',()=>closeMapModal(el('hydroModelModal')));
  el('hydroModelModal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeMapModal(e.currentTarget);});
  function renderObservedStatistics() {
    el('hydroObservedStatistics').innerHTML=workbook ? `<h4>Statistik debit pengamatan (m³/det)</h4>${workbook.sheets.map(sheet=>{
      if(sheet.error) return `<p>${escape(sheet.name)}: ${escape(sheet.error)}</p>`;
      const s=sheet.statistics;
      return `<details open><summary>${escape(sheet.name)}</summary><p>${yearRanges(sheet.records.map(r=>r.year))}; ${s.count} data valid; ${s.missing_count} kosong; ${s.zero_count} debit nol.</p><p>Minimum ${number(s.min)}; maksimum ${number(s.max)}; rerata ${number(s.mean)}; median ${number(s.median)}; simpangan baku sampel ${number(s.std)}; CV ${number(s.cv)}.</p><div class="hydro-model-table"><table><thead><tr>${Object.keys(s.quantiles).map(q=>`<th scope="col">${q}</th>`).join('')}</tr></thead><tbody><tr>${Object.values(s.quantiles).map(v=>`<td>${number(v)}</td>`).join('')}</tr></tbody></table></div></details>`;
    }).join('')}<p class="hydro-model-note">Data kosong dikecualikan; debit nol tetap dihitung. Debit andalan memakai PERCENTILE.EXC(data, 1−p), setiap periode berbobot sama; bukan FDC harian. n.a. berarti jumlah data belum cukup atau statistik tidak terdefinisi.</p>` : '';
  }
  async function uploadWorkbook(file) {
    const token=++uploadRevision;
    workbook=null; sourceFile=''; mapping.clear();invalidate();renderDonors();renderObservedStatistics();
    if(!file)return;
    el('hydroWorkbookInfo').textContent='Memeriksa workbook…';
    try {
      if(file.size>10*1024*1024)throw new Error('Ukuran Excel maksimal 10 MB.');
      const response=await fetch('/api/hydro-model/workbook?allow_missing=true',{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:file});
      const payload=await window.readApiJsonResponse(response,'Gagal membaca Excel.');
      if(!response.ok)throw new Error(payload.detail||'Gagal membaca Excel.');
      if(token!==uploadRevision)return;
      workbook=payload;sourceFile=file.name;
      invalidate();
      el('hydroWorkbookInfo').textContent=`${file.name}: ${payload.sheets.length} sheet. ${payload.sheets.filter(s=>!s.error).length} sheet valid.`;
      renderDonors();renderObservedStatistics();
    } catch(error) {
      if(token===uploadRevision) {
        el('hydroWorkbookInfo').textContent = error instanceof TypeError && /fetch/i.test(error.message)
          ? 'Tidak dapat terhubung ke layanan aplikasi. Periksa server lalu pilih file lagi.'
          : error.message;
      }
    }
  }
  el('hydroWorkbook').addEventListener('change',event=>uploadWorkbook(event.target.files[0]));
  el('chooseHydroWorkbook').addEventListener('click',()=>el('hydroWorkbook').click());
  const dropzone=el('hydroWorkbookDropzone');
  for(const eventName of ['dragenter','dragover'])dropzone.addEventListener(eventName,event=>{event.preventDefault();dropzone.classList.add('is-dragover');});
  for(const eventName of ['dragleave','drop'])dropzone.addEventListener(eventName,event=>{event.preventDefault();dropzone.classList.remove('is-dragover');});
  dropzone.addEventListener('drop',event=>uploadWorkbook(event.dataTransfer?.files?.[0]));
  el('hydroPreset').addEventListener('change',event=>{
    const presets={area:[],climate:['rainfall'],hydro:['aquifer'],physical:['aquifer','soil','landcover','terrain','rainfall']};
    const active=presets[event.target.value];
    if(active)document.querySelectorAll('.hydro-group').forEach(i=>i.checked=active.includes(i.value));
    invalidate();updateInfo();
  });
  document.querySelectorAll('.hydro-group').forEach(i=>i.addEventListener('change',()=>{el('hydroPreset').value='custom';invalidate();updateInfo();}));
  for(const id of ['hydroExponent','hydroSoilDepth','hydroSourceNotes','hydroStartYear','hydroEndYear','hydroMlAlgorithm','hydroWarmupYears'])el(id).addEventListener('input',()=>{invalidate();updateInfo();});
  el('hydroMockMode').addEventListener('change',()=>{invalidate(undefined,true);updateInfo();});
  el('hydroMockBounds').addEventListener('input',()=>invalidate(undefined,true));
  el('hydroLoadGisParameters').addEventListener('click',async()=>{
    const token=++mockLoadRevision, geometry=fingerprint();
    mockLoading=true;updateInfo();el('hydroMockParameterStatus').textContent='Menghitung parameter GIS setiap DTA…';
    try{
      const input={model:'mock',points:available().map(({point_id,lon,lat,source,label,river_name})=>({point_id,lon,lat,source,label,river_name})),
        snap_radius_m:Number(snapRadiusEl.value),boundary_match_m:Number(boundaryMatchEl.value)};
      const response=await fetch('/api/hydro-model/parameters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});
      const payload=await window.readApiJsonResponse(response,'Gagal membaca parameter GIS.');
      if(!response.ok)throw new Error(payload.detail||'Gagal membaca parameter GIS.');
      if(token!==mockLoadRevision||geometry!==fingerprint())return;
      mockGis=payload;mockValues.clear();
      payload.points.forEach(p=>mockValues.set(p.point_id,{smc_multiplier:1,infiltration:p.soil_parameters.infiltration,k30:p.recession_parameters.k30}));
      invalidate(undefined,true);renderMockValues();
      el('hydroMockParameterStatus').textContent=`Parameter GIS siap untuk ${payload.points.length} DTA.`;
    }catch(error){if(token===mockLoadRevision)el('hydroMockParameterStatus').textContent=error.message;}
    finally{mockLoading=false;updateInfo();}
  });
  for(const input of [snapRadiusEl,boundaryMatchEl])input.addEventListener('change',()=>window.refreshHydroModelUiState());
  el('runHydroModel').addEventListener('click',async()=>{
    let progress;
    try {
      const input=recipe(), token=revision, geometry=fingerprint();
      running=true;updateInfo();progress=window.startAnalysisProgress?.(el('hydroStatus'),'Menghitung parameter DTA dan simulasi debit…');
      const response=await fetch('/api/hydro-model',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});
      const payload=await window.readApiJsonResponse(response,'Simulasi gagal.');
      if(!response.ok)throw new Error(payload.detail||'Simulasi gagal.');
      if(token!==revision||geometry!==fingerprint()){el('hydroStatus').textContent='Input berubah selama perhitungan. Jalankan ulang simulasi.';return;}
      result=payload;resultRecipe=input;previousGeometry=geometry;progress?.complete?.();
      if(input.model==='mock') {
        mockSimulated=true;
        if(!mockGis) {
          mockGis={points:payload.results};
          payload.results.forEach(p=>mockValues.set(p.point_id,{smc_multiplier:1,infiltration:p.soil_parameters.infiltration,k30:p.recession_parameters.k30}));
          renderMockValues();
          el('hydroMockParameterStatus').textContent='Parameter GIS siap untuk kalibrasi.';
        }
      }
      if(window.ensureInteractiveChartRuntime)await window.ensureInteractiveChartRuntime().catch(()=>{});
      if(token!==revision||geometry!==fingerprint())return;
      el('hydroStatus').textContent=`Simulasi selesai untuk ${payload.results.length} DTA. Buka Unduh Hasil untuk mendapatkan Excel.`;
      showResult();downloadState();
    }catch(error){progress?.fail?.();el('hydroStatus').textContent=error.message;}
    finally{running=false;updateInfo();}
  });
  el('downloadHydroModel').addEventListener('change',()=>updateDownloadSummary());
  el('downloadBtn').addEventListener('click',()=>{window.refreshHydroModelUiState();updateDownloadSummary();});
  window.refreshHydroModelUiState();
})();
