// 새 프로젝트 입력 검사. 기획 문서는 PDF만 받는다 (지금 백엔드가 PDF만 받고 다른 양식은 입력 점검에서 반려한다).

export function isPdf(name: string): boolean {
  return /\.pdf$/i.test(name)
}

export function isZip(name: string): boolean {
  return /\.zip$/i.test(name)
}

/** 올린 파일을 PDF와 받을 수 없는 파일로 나눈다 */
export function splitPlans<F extends { name: string }>(files: F[]): { pdfs: F[]; rejected: F[] } {
  return { pdfs: files.filter((f) => isPdf(f.name)), rejected: files.filter((f) => !isPdf(f.name)) }
}

/** 저장소 주소: http(s):// 로 시작하고 호스트가 있어야 한다 */
export function isRepoUrl(s: string): boolean {
  try {
    const u = new URL(s.trim())
    return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.hostname
  } catch {
    return false
  }
}

/** 이름을 비워 두면 첫 기획서 파일 이름 (확장자 뺌) */
export function defaultName(plans: { name: string }[]): string {
  return plans[0]?.name.replace(/\.[^.]+$/, '') ?? ''
}

export function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`
}

/** 분석 시작에 빠진 것. 다 있으면 빈 목록 */
export function missingInputs(i: { plans: unknown[]; zip: unknown | null; repoUrl: string }): string[] {
  const out: string[] = []
  if (!i.plans.length) out.push('기획서 PDF를 올려 주세요.')
  if (!i.zip && !i.repoUrl.trim()) out.push('소스코드 압축 파일(.zip)을 올리거나 저장소 주소를 넣어 주세요.')
  else if (!i.zip && !isRepoUrl(i.repoUrl)) out.push('저장소 주소는 https:// 로 시작해야 합니다.')
  return out
}
