// PDF.js 불러오기, 쪽 그리기, 글자 조각 읽기. PDF.js는 크기가 커서 처음 쓸 때만 불러온다.
import type { PDFDocumentProxy } from 'pdfjs-dist'
import type { PageText, TextItem } from '../lib/quoteLocate.ts'

/** 썸네일 폭 (카드 최대 약 300px의 두 배). 요약 카드와 왼쪽 화면 목록이 같은 그림을 나눠 쓴다. */
export const THUMB_WIDTH = 600
/** 기획서 페이지 폭. "크게 보기"(170%)에서도 흐려지지 않게 넉넉히 */
export const PAGE_WIDTH = 2000

let pdfjsPromise: Promise<typeof import('pdfjs-dist')> | null = null
const docs = new Map<string, Promise<PDFDocumentProxy>>()

function pdfjs() {
  pdfjsPromise ??= Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')])
    .then(([lib, worker]) => {
      lib.GlobalWorkerOptions.workerSrc = worker.default
      return lib
    })
  return pdfjsPromise
}

export function openPdf(url: string): Promise<PDFDocumentProxy> {
  let doc = docs.get(url)
  if (!doc) {
    doc = pdfjs().then((lib) => lib.getDocument({ url }).promise)
    docs.set(url, doc)
    doc.catch(() => docs.delete(url))
  }
  return doc
}

async function getPage(url: string, pageNo: number) {
  const doc = await openPdf(url)
  return doc.getPage(Math.min(Math.max(1, pageNo), doc.numPages))
}

/** 그 쪽을 width 픽셀 폭으로 그려 이미지 주소(data URL)로 돌려준다 */
export async function renderPageImage(url: string, pageNo: number, width: number): Promise<string> {
  const page = await getPage(url, pageNo)
  const viewport = page.getViewport({ scale: width / page.getViewport({ scale: 1 }).width })
  const canvas = document.createElement('canvas')
  canvas.width = Math.ceil(viewport.width)
  canvas.height = Math.ceil(viewport.height)
  await page.render({ canvas, viewport }).promise
  return canvas.toDataURL('image/jpeg', 0.85)
}

/** 그 쪽의 글자 조각과 위치 (배율 1, 위쪽 기준). 원문 찾기에 쓴다. */
export async function getPageText(url: string, pageNo: number): Promise<PageText> {
  const [lib, page] = await Promise.all([pdfjs(), getPage(url, pageNo)])
  const vp = page.getViewport({ scale: 1 })
  const content = await page.getTextContent()
  const items: TextItem[] = []
  for (const it of content.items) {
    if (!('str' in it) || !it.str) continue
    const t = lib.Util.transform(vp.transform, it.transform)
    const size = Math.hypot(t[2], t[3])
    // t[5]는 글자 바닥선. 위로 글자 크기만큼, 아래로 조금(받침·내림 글자) 더 잡는다.
    items.push({ str: it.str, x: t[4], y: t[5] - size * 0.9, w: it.width * vp.scale, h: size * 1.15 })
  }
  return { page: pageNo, width: vp.width, height: vp.height, items }
}
