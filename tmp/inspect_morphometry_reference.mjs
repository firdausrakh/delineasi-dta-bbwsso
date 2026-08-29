import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
import fs from 'node:fs/promises';

const source = 'C:/Users/Server/Desktop/contoh excel morfometri.xlsx';
const blob = await FileBlob.load(source);
const workbook = await SpreadsheetFile.importXlsx(blob);
console.log((await workbook.inspect({kind:'workbook,sheet,table', maxChars:8000, tableMaxRows:30, tableMaxCols:12})).ndjson);
for (const sheet of workbook.worksheets.items) {
  const preview = await workbook.render({sheetName:sheet.name, autoCrop:'all', scale:1.5, format:'png'});
  await fs.writeFile(`tmp/spreadsheet_reference_${sheet.name}.png`, new Uint8Array(await preview.arrayBuffer()));
  console.log(`Rendered ${sheet.name}`);
}
