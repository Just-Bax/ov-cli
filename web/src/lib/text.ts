const KIBI = 1024
const MEBI = KIBI * KIBI

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

export function fileSize(bytes: number): string {
  const kilobytes = Math.max(1, Math.ceil(bytes / KIBI))
  return kilobytes >= KIBI ? `${(bytes / MEBI).toFixed(1)} MB` : `${kilobytes} KB`
}
