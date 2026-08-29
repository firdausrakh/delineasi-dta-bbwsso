import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const path = 'outputs/characteristics-v16-verification/Karakteristik_DTA_Pungangan.xlsx';
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
console.log((await workbook.inspect({kind:'workbook,sheet,table', maxChars:12000, tableMaxRows:12, tableMaxCols:6})).ndjson);
console.log((await workbook.inspect({kind:'match', searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A', options:{useRegex:true,maxResults:100}, summary:'formula error scan'})).ndjson);
for (const sheet of workbook.worksheets.items) {
  const preview = await workbook.render({sheetName:sheet.name, autoCrop:'all', scale:1.25, format:'png'});
  await fs.writeFile(`tmp/characteristics_${sheet.name.replaceAll(' ','_')}.png`, new Uint8Array(await preview.arrayBuffer()));
}
