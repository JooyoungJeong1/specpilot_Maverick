// PDF 쪽 그림과 글자를 TanStack Query로 캐시한다. 같은 쪽은 화면을 오가도 다시 그리지 않는다.
import { useQuery } from '@tanstack/react-query'
import { getPageText, renderPageImage } from './pdf.ts'

export function usePageImage(url: string | null, page: number | undefined, width: number) {
  return useQuery({
    queryKey: ['page-image', url, page, width],
    queryFn: () => renderPageImage(url!, page!, width),
    enabled: !!url && !!page,
    staleTime: Infinity,
  })
}

export function usePageTexts(url: string | null, pages: number[]) {
  return useQuery({
    queryKey: ['page-text', url, pages.join(',')],
    queryFn: () => Promise.all(pages.map((p) => getPageText(url!, p))),
    enabled: !!url && pages.length > 0,
    staleTime: Infinity,
  })
}
