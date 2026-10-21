"""One workbook, one sheet per target, using the application's OOXML exporter."""
from __future__ import annotations

import io
import json
import zipfile
import calendar
from xml.sax.saxutils import quoteattr, escape
import math

from api.services.characteristics_workbook import ExcelFormula, _cell, _column_name
from api.services.hss_workbook import _safe_sheet_name
from api.services.hydro_model import MONTHS, EXCEEDANCES


def _headers():
    return [['Tahun'] + [month if period % 2 == 0 else '' for month in MONTHS for period in (0, 1)],
            [''] + ['I', 'II'] * 12]


def _literal_cell(ref, value, style=0):
    """Keep missing observations empty and preserve JSON/parameter names verbatim."""
    if value is None:
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
        return f'<c r="{ref}" s="{style or 2}"><v>{value:.17g}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def _quote_sheet(name):
    return "'" + name.replace("'", "''") + "'"


def _transfer_formula(result, year, period, payload, reference_sheets, reference_rows):
    """Return the transparent weighted-DAR calculation for one target cell."""
    column = _column_name(period + 2)
    terms = []
    for reference in result['donors']:
        source_row = reference_rows[reference['point_id']][year]
        ratio = result['area_km2'] / reference['area_km2']
        terms.append(f'{_quote_sheet(reference_sheets[reference["point_id"]])}!{column}{source_row}*{reference["weight"]:.15g}*({ratio:.15g}^{payload["b"]:.15g})')
    return '+'.join(terms)


def _volume_formula(records):
    yearly = []
    for row, record in enumerate(records, 3):
        periods = []
        for period in range(24):
            days = 15 if period % 2 == 0 else calendar.monthrange(record['year'], period // 2 + 1)[1] - 15
            periods.append(f'{_column_name(period + 2)}{row}*{days}')
        yearly.append('(' + '+'.join(periods) + ')')
    return '(' + '+'.join(yearly) + ')*86400'


def _reference_sheet(reference):
    rows = _headers() + [[record['year'], *record['values']] for record in reference['records']]
    for row_number, note in ((1, 'Pengisian dilakukan pada kolom kuning'), (2, 'Maksimal 100 tahun data'),
                             (4, 'Isikan tahun data beserta debitnya setiap tengah bulan')):
        while len(rows) < row_number:
            rows.append([])
        rows[row_number - 1] += [''] * (26 - len(rows[row_number - 1])) + [note]
    xml_rows = []
    for r, values in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(values, 1):
            style = 7 if (r, c) == (1, 27) else (1 if r <= 2 else (5 if c == 1 else 6))
            cells.append(_literal_cell(f'{_column_name(c)}{r}', value, style))
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    merges = ['A1:A2', 'AA1:AE1'] + [f'{_column_name(c)}1:{_column_name(c + 1)}1' for c in range(2, 26, 2)]
    return ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetPr><tabColor rgb="FFFFFF00"/></sheetPr><dimension ref="A1:AE{len(rows)}"/><sheetViews><sheetView workbookViewId="0"><pane xSplit="1" ySplit="2" topLeftCell="B3" activePane="bottomRight" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>'
            '<cols><col min="1" max="1" width="9.140625"/><col min="2" max="25" width="6.7109375" customWidth="1"/><col min="26" max="16384" width="9.140625"/></cols>'
            f'<sheetData>{"".join(xml_rows)}</sheetData><mergeCells count="{len(merges)}">' + ''.join(f'<mergeCell ref="{merge}"/>' for merge in merges) + '</mergeCells>'
            '<pageSetup orientation="landscape" paperSize="9" fitToWidth="1" fitToHeight="0"/></worksheet>')


def _sheet(result, payload, reference_sheets, reference_rows):
    records = result['records']
    last = len(records) + 2
    rows = _headers()
    rows[0] += [''] * (26 - len(rows[0])) + ['Kolom hijau merupakan hasil model']
    for record in records:
        rows.append([record['year'], *[ExcelFormula(_transfer_formula(result, record['year'], period, payload, reference_sheets, reference_rows), value)
                                      for period, value in enumerate(record['values'])]])
    rows.append([])
    for p in EXCEEDANCES:
        rows.append([f'Q{p}', *[ExcelFormula(f'_xlfn.PERCENTILE.EXC({col}$3:{col}${last},{1-p/100:.10g})', s['quantiles'][f'Q{p}'])
                               if s['quantiles'][f'Q{p}'] is not None else 'n.a.'
                               for col, s in zip([_column_name(i) for i in range(2, 26)], result['period_statistics'])]])
    for key, label, fn in [('mean', 'Rerata', 'AVERAGE'), ('min', 'Minimum', 'MIN'), ('max', 'Maksimum', 'MAX'),
                           ('median', 'Median', 'MEDIAN'), ('std', 'Simpangan baku sampel', 'STDEV'), ('cv', 'Koefisien variasi', None)]:
        rows.append([label, *[ExcelFormula(f'{fn}({col}$3:{col}${last})' if fn else f'IF(AVERAGE({col}$3:{col}${last})=0,"n.a.",STDEV({col}$3:{col}${last})/AVERAGE({col}$3:{col}${last}))', s[key]) if s[key] is not None else 'n.a.'
                              for col, s in zip([_column_name(i) for i in range(2, 26)], result['period_statistics'])]])
    rows.append(['Jumlah nilai', *[ExcelFormula(f'COUNT({col}$3:{col}${last})', s['count'])
                                  for col, s in zip([_column_name(i) for i in range(2, 26)], result['period_statistics'])]])
    rows.append(['Jumlah nol', *[ExcelFormula(f'COUNTIF({col}$3:{col}${last},0)', s['zero_count'])
                                for col, s in zip([_column_name(i) for i in range(2, 26)], result['period_statistics'])]])
    summary_metrics = [
        ('mean', 'Rerata', f'AVERAGE(B3:Y{last})'), ('min', 'Minimum', f'MIN(B3:Y{last})'),
        ('max', 'Maksimum', f'MAX(B3:Y{last})'), ('median', 'Median', f'MEDIAN(B3:Y{last})'),
        ('std', 'Simpangan baku sampel', f'STDEV(B3:Y{last})'),
        ('cv', 'Variansi', f'IF(AVERAGE(B3:Y{last})=0,"n.a.",STDEV(B3:Y{last})/AVERAGE(B3:Y{last}))'),
        ('count', 'Jumlah nilai', f'COUNT(B3:Y{last})'), ('zero_count', 'Jumlah nol', f'COUNTIF(B3:Y{last},0)')]
    info = [['Ringkasan', ''],
            *[[f'Q{p}%', ExcelFormula(f'_xlfn.PERCENTILE.EXC(B3:Y{last},{1-p/100:.10g})', result['statistics']['quantiles'][f'Q{p}'])] for p in EXCEEDANCES],
            *[[label, ExcelFormula(formula, result['statistics'][key]) if result['statistics'][key] is not None else 'n.a.']
              for key, label, formula in summary_metrics],
            ['Luas (km²)', result['area_km2']], ['Metode', payload['method']], ['Eksponen b', payload['b']], ['Satuan', payload['unit']],
            ['Catatan', payload.get('source_notes', '')], ['Parameter', ', '.join(payload['groups']) or 'Luas saja'], ['Tanah', f'Kedalaman {payload["soil_depth_cm"]} cm'],
            ['Peringatan', '; '.join(result['warnings']) or '—']]
    for i, extra in enumerate(info, 3):
        while len(rows) <= i:
            rows.append([])
        rows[i] += [''] * (26 - len(rows[i])) + extra
    rows += [[], ['Referensi', 'Sheet sumber', 'Luas (km²)', 'Bobot', 'Jarak kemiripan', 'Peringatan']]
    for donor in result['donors']:
        rows.append([donor['label'], donor['sheet'], donor['area_km2'], donor['weight'], donor['distance'], '; '.join(donor['warnings'])])
    rows += [[], ['Parameter spasial target', json.dumps(result.get('features', {}), ensure_ascii=False)]]
    for donor in result['donors']:
        rows.append([f'Parameter {donor["label"]}', json.dumps(donor['features'], ensure_ascii=False)])
    rows += [[], ['Konteks hidrogeologi (tanpa bobot; persentase terhadap seluruh luas DTA)'],
             ['DTA', 'Peran', 'Konteks', 'Kelas / nama', 'Luas DTA (%)', 'Cakupan (%)']]
    for index, point in enumerate([result, *result['donors']]):
        for key, label in [('cat', 'CAT'), ('lithology', 'Litologi')]:
            context = point.get('hydrogeology_context', {}).get(key, {})
            classes = context.get('classes', {})
            for category, fraction in classes.items():
                rows.append([point['label'], 'Target' if index == 0 else 'Referensi', label, category,
                             fraction * 100, context['coverage'] * 100])
            if not classes:
                rows.append([point['label'], 'Target' if index == 0 else 'Referensi', label,
                             'Tidak ada irisan terpetakan' if context.get('available') else 'Data tidak tersedia',
                             '', context['coverage'] * 100 if context.get('available') else 'n.a.'])
    rows.append(['Catatan konteks', 'Kesamaan CAT belum membuktikan konektivitas air tanah. CAT dan litologi tidak menambah bobot atau debit.'])
    if result.get('rainfall'):
        rows += [[], ['Hujan tengah bulanan', payload['rainfall_convention']], ['Jarak hujan', 'sum(abs(Ptarget-P_referensi))/sum(Ptarget+P_referensi); kedua deret nol: jarak 0.']]
        for point in [result, *result['donors']]:
            rain = point['rainfall']
            rows += [[], [f'Hujan {point["label"]}', rain['unit']], ['Sumber', rain['source']],
                     ['SHA256 sumber', rain['source_sha256']], ['Deskripsi sumber', rain['description']],
                     ['Rerata tahunan (mm)', rain['mean_annual_mm']], ['Cakupan minimum (%)', rain['coverage_min']*100],
                     ['Metode spasial', rain['spatial_method']], ['Catatan kualitas', rain['quality_note']],
                     ['Tahun'] + [f'{month} {half}' for month in MONTHS for half in ('I', 'II')]]
            rows += [[r['year'], *r['values']] for r in rain['records']]
    if payload.get('validation'):
        rows += [[], ['Validasi bergiliran referensi (LOOCV)'], ['DTA uji', 'Q50 pengamatan', 'Q50 prediksi', 'APE Q50 (%)', 'RMSE (m³/det)', 'Bias (m³/det)', 'Q50 luas saja', 'APE luas saja (%)']]
        for v in payload['validation']:
            rows.append([v['label'], v['observed_q50'], v['predicted_q50'], v['ape_q50_pct'], v['rmse'], v['bias'], v['baseline_q50'], v['baseline_ape_q50_pct']])
        rows.append(['Catatan validasi', payload['validation_note']])
    rows += [[], ['Sensitivitas transfer referensi (bukan interval kepercayaan)'], ['Tahun'] + [f'{m} {half}' for m in MONTHS for half in ('I', 'II')]]
    for i, record in enumerate(records):
        rows.append([f'{record["year"]} minimum', *result['donor_transfer_range']['min'][i]])
        rows.append([f'{record["year"]} maksimum', *result['donor_transfer_range']['max'][i]])
    xml_rows = []
    for r, values in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(values, 1):
            if (r, c) == (1, 27):
                style = 8
            elif (r, c) == (4, 27):
                style = 9
            elif 4 <= r <= 31 and c in (27, 28):
                style = 10
            elif r <= 2:
                style = 1
            elif 3 <= r <= last and c == 1:
                style = 4
            elif 3 <= r <= last and 2 <= c <= 25:
                style = 3
            else:
                style = 0
            if isinstance(value, (float, int)):
                numeric_style = style or (0 if isinstance(value, int) else 2)
                cells.append(f'<c r="{_column_name(c)}{r}" s="{numeric_style}"><v>{value:.17g}</v></c>')
            else:
                cells.append(_cell(f'{_column_name(c)}{r}', value, style))
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    merges = ['A1:A2', 'AA1:AE1', 'AB25:AE25', 'AB26:AE26', 'AB27:AE27', 'AB28:AE28', 'AB29:AE29', 'AB30:AE30', 'AA31:AA34', 'AB31:AE34'] + [f'{_column_name(c)}1:{_column_name(c+1)}1' for c in range(2, 26, 2)]
    return ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetPr><tabColor rgb="FF92D050"/></sheetPr><dimension ref="A1:AE{len(rows)}"/><sheetViews><sheetView workbookViewId="0"><pane xSplit="1" ySplit="2" topLeftCell="B3" activePane="bottomRight" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>'
            '<cols><col min="1" max="1" width="9.140625"/><col min="2" max="25" width="6.7109375" customWidth="1"/><col min="26" max="16384" width="9.140625"/></cols>'
            f'<sheetData>{"".join(xml_rows)}</sheetData><mergeCells count="{len(merges)}">'+''.join(f'<mergeCell ref="{m}"/>' for m in merges)+'</mergeCells>'
            '<pageSetup orientation="landscape" paperSize="9" fitToWidth="1" fitToHeight="0"/></worksheet>')


def _runoff_sheet(result, payload):
    rows = _headers() + [[r['year'], *r['values']] for r in result['records']]
    rows += [[], ['Model', payload['method']], ['DTA', result['label']], ['Luas (km²)', result['area_km2']],
             ['Sumber debit', payload.get('source_file','')], ['Catatan sumber', payload.get('source_notes','')],
             ['Validasi', payload['validation_note']]]
    if payload.get('model')=='mock':
        rows += [['Pemanasan (tahun)',result['model_parameters']['warmup_years']],
                 ['Awal simulasi iklim',result['climate']['simulation_start']],
                 ['Awal keluaran setelah pemanasan',result['climate']['output_start']],
                 ['Perlakuan pemanasan','Tampungan diteruskan; dikeluarkan dari hasil, statistik, kalibrasi, dan validasi. Sheet pengamatan menyimpan input asli.']]
    for title, values in [('Parameter model', result['model_parameters']), ('Parameter tanah GIS',result['soil_parameters']),
                          ('Statistik hasil',result['statistics'])]:
        rows += [[], [title]]
        for key,value in values.items():
            rows.append([key,json.dumps(value,ensure_ascii=False,allow_nan=False) if isinstance(value,(dict,list)) else value])
    rows += [[], ['Konteks hidrogeologi', json.dumps(result.get('hydrogeology_context',{}),ensure_ascii=False)]]
    rows += [['Peringatan',w] for w in result['warnings']]
    if result.get('observation_comparison'):
        rows += [[],['Perbandingan pengamatan',result['comparison_note']]]
        rows += [[key,value] for key,value in result['observation_comparison'].items()]
    rows += [[], ['Hujan dan ET0',result['climate']['method']],
             ['Sumber hujan',result['climate']['rainfall_source']], ['Cakupan hujan minimum',result['climate']['coverage_min']],
             ['Sumber ET0',json.dumps(result['climate']['et0'],ensure_ascii=False)],
             ['Tanggal','Tahun','Periode','Hari','P (mm)','ET0 (mm)','Hari hujan ≥1 mm']]
    rows += [[r['start'],r['year'],r['period']+1,r['days'],r['p_mm'],r['et0_mm'],r['wet_days']] for r in result['climate']['rows']]
    if result['water_balance']:
        keys=['start','p_mm','et0_mm','aet_mm','soil_mm','groundwater_mm','recharge_mm','direct_mm','baseflow_mm','runoff_mm','balance_error_mm']
        rows += [[], ['Neraca air Mock (mm)'], keys]
        rows += [[r[k] for k in keys] for r in result['water_balance']]
    rows += [[], ['Validasi independen'], ['DTA','Skema','n','RMSE m³/det','Bias m³/det','NSE','KGE','PBIAS %']]
    rows += [[v['label'],v['scheme'],v['count'],v['rmse'],v['bias'],v['nse'],v['kge'],v['pbias_pct']] for v in payload['validation']]
    xml_rows=[]
    for i, values in enumerate(rows,1):
        cells=''.join(_literal_cell(f'{_column_name(j)}{i}',v,1 if i<=2 else 3 if i<=len(result['records'])+2 else 0) for j,v in enumerate(values,1))
        xml_rows.append(f'<row r="{i}">{cells}</row>')
    merges=['A1:A2']+[f'{_column_name(c)}1:{_column_name(c+1)}1' for c in range(2,26,2)]
    return ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane xSplit="1" ySplit="2" topLeftCell="B3" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>'
            '<cols><col min="1" max="1" width="24" customWidth="1"/><col min="2" max="25" width="16" customWidth="1"/></cols>'
            f'<sheetData>{"".join(xml_rows)}</sheetData><mergeCells count="{len(merges)}">'+''.join(f'<mergeCell ref="{m}"/>' for m in merges)+'</mergeCells></worksheet>')


def workbook_bytes(payload):
    if not payload.get('results'):
        raise ValueError('Jalankan simulasi terlebih dahulu.')
    used = set()
    references = payload.get('references', [])
    reference_sheets = {reference['point_id']: _safe_sheet_name(reference['label'], used) for reference in references}
    reference_rows = {reference['point_id']: {record['year']: row for row, record in enumerate(reference['records'], 3)} for reference in references}
    target_sheets = {result['point_id']: _safe_sheet_name(result['label'], used) for result in payload['results']}
    sheets = [(reference_sheets[reference['point_id']], _reference_sheet(reference)) for reference in references]
    sheets += [(target_sheets[result['point_id']], _runoff_sheet(result,payload) if payload.get('model') in ('mock','ml')
                else _sheet(result, payload, reference_sheets, reference_rows)) for result in payload['results']]
    style = ('<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="164" formatCode="[&lt;10]0.00;[&lt;100]0.0;0"/></numFmts>'
             '<fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><name val="Arial"/></font></fonts>'
             '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF92D050"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/></patternFill></fill></fills>'
             '<borders count="2"><border/><border><left style="thin"><color indexed="64"/></left><right style="thin"><color indexed="64"/></right><top style="thin"><color indexed="64"/></top><bottom style="thin"><color indexed="64"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="11">'
             '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
             '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
             '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
             '<xf numFmtId="164" fontId="0" fillId="2" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
             '<xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
             '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
             '<xf numFmtId="164" fontId="0" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
             '<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
             '<xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
             '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
             '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
             '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        overrides = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1))
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+overrides+'</Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="book" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        entries = ''.join(f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="s{i}"/>' for i, (name, _) in enumerate(sheets, 1))
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+entries+'</sheets><calcPr fullCalcOnLoad="1"/></workbook>')
        rels = ''.join(f'<Relationship Id="s{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1))
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+rels+'<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml', style)
        for i, (_, xml) in enumerate(sheets, 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', xml)
    return output.getvalue()
