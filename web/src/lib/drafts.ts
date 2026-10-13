import { reportError } from '@/components/common/Toasts'

const TEXT_PREFIX = 'ov-agent.draft.'
const DB_NAME = 'ov-agent'
const STORE = 'draft-files'
const DB_VERSION = 1

type StoredFile = { name: string; type: string; lastModified: number; data: Blob }

export function loadText(key: string): string {
  return localStorage.getItem(TEXT_PREFIX + key) ?? ''
}

export function saveText(key: string, text: string): void {
  if (text) localStorage.setItem(TEXT_PREFIX + key, text)
  else localStorage.removeItem(TEXT_PREFIX + key)
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => request.result.createObjectStore(STORE)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Cannot open the draft store.'))
  })
}

async function run<T>(
  mode: IDBTransactionMode,
  act: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await open()
  try {
    return await new Promise<T>((resolve, reject) => {
      const request = act(db.transaction(STORE, mode).objectStore(STORE))
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error ?? new Error('Draft store request failed.'))
    })
  } finally {
    db.close()
  }
}

export async function loadFiles(key: string): Promise<File[]> {
  const stored = (await run('readonly', (s) => s.get(key))) as StoredFile[] | undefined
  return (stored ?? []).map(
    (f) => new File([f.data], f.name, { type: f.type, lastModified: f.lastModified }),
  )
}

export async function saveFiles(key: string, files: File[]): Promise<void> {
  if (!files.length) {
    await run('readwrite', (s) => s.delete(key))
    return
  }

  const stored: StoredFile[] = files.map((f) => ({
    name: f.name,
    type: f.type,
    lastModified: f.lastModified,
    data: f,
  }))
  await run('readwrite', (s) => s.put(stored, key))
}

export function forgetDraft(key: string): void {
  saveText(key, '')
  void saveFiles(key, []).catch(reportError)
}
