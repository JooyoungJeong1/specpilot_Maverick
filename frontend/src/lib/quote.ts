/** 함의 단위의 근거 원문들. " / "로 이어져 있다 (schema.quote_segments와 같은 규칙) */
export function quoteSegments(quote: string | null | undefined): string[] {
  if (!quote || !quote.trim()) return []
  return quote.split(' / ').map((s) => s.trim()).filter(Boolean)
}
