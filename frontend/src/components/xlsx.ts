// 브라우저에서 xlsx 만들기 (SheetJS). 크기가 커서 내려받을 때만 불러온다.
import type { Sheet } from '../lib/sheets.ts'

/** 글자 수로 열 폭을 잡는다 (한글은 두 칸). 너무 넓지 않게 60칸까지 */
function colWidths(sheet: Sheet): { wch: number }[] {
  const width = (v: unknown) => Math.max(...String(v ?? '').split('\n').map((line) =>
    [...line].reduce((n, c) => n + (c.charCodeAt(0) > 0x2e80 ? 2 : 1), 0)))
  return sheet.header.map((h, i) => ({ wch: Math.min(60, Math.max(width(h), ...sheet.rows.map((r) => width(r[i]))) + 2) }))
}

export async function downloadWorkbook(fileName: string, sheets: Sheet[]): Promise<void> {
  const XLSX = await import('xlsx')
  const wb = XLSX.utils.book_new()
  for (const s of sheets) {
    const ws = XLSX.utils.aoa_to_sheet([s.header, ...s.rows])
    ws['!cols'] = colWidths(s)
    XLSX.utils.book_append_sheet(wb, ws, s.name)
  }
  XLSX.writeFile(wb, fileName)
}
