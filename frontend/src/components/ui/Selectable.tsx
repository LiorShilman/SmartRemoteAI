import { useEffect, useState, type ReactNode } from 'react'
import { ListChecks, Trash2, X } from 'lucide-react'
import { Key } from './Primitives'

/** Multi-select state for a list of items identified by string ids. */
export function useSelection(ids: string[]) {
  const [on, setOn] = useState(false)
  const [sel, setSel] = useState<string[]>([])
  const key = ids.join('|')
  // Items can disappear (deleted, finished, refreshed): never keep a selection of something that is gone.
  useEffect(() => { setSel((s) => s.filter((x) => ids.includes(x))) }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return {
    on, sel,
    allSelected: ids.length > 0 && sel.length === ids.length,
    toggle: (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id])),
    start: () => setOn(true),
    stop: () => { setOn(false); setSel([]) },
    selectAll: () => setSel(ids),
    clear: () => setSel([]),
  }
}
export type Selection = ReturnType<typeof useSelection>

interface ToolbarProps {
  s: Selection
  total: number
  /** Deletes exactly the selected ids. */
  onDeleteSelected: (ids: string[]) => void | Promise<void>
  /** Clears everything this list may clear (e.g. all finished items). */
  onClearAll: () => void | Promise<void>
  clearAllLabel?: string
  /** Shown on the delete button, e.g. "מחק" or "מחק / בטל". */
  deleteLabel?: string
}

/** The row of buttons above a history list: select mode, delete selected, clear all. */
export function SelectToolbar({ s, total, onDeleteSelected, onClearAll, clearAllLabel = 'נקה הכל', deleteLabel = 'מחק' }: ToolbarProps) {
  if (!s.on) {
    return (
      <div className="flex flex-wrap gap-2 justify-end mb-2">
        <Key label="בחירה מרובה" className="px-3 h-10 text-sm" disabled={total === 0} onClick={s.start}>
          <ListChecks size={16} /> בחירה
        </Key>
        <Key label={clearAllLabel} className="px-3 h-10 text-sm" disabled={total === 0} onClick={() => void onClearAll()}>
          <Trash2 size={16} /> {clearAllLabel}
        </Key>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap gap-2 items-center mb-2" role="toolbar" aria-label="פעולות על הנבחרים">
      <span className="text-sm text-muted me-auto" aria-live="polite">{s.sel.length} נבחרו</span>
      <Key label={s.allSelected ? 'בטל בחירת הכל' : 'בחר הכל'} className="px-3 h-10 text-sm" onClick={s.allSelected ? s.clear : s.selectAll}>
        {s.allSelected ? 'בטל בחירה' : 'בחר הכל'}
      </Key>
      <Key label={`${deleteLabel} את הנבחרים`} variant="danger" className="px-3 h-10 text-sm" disabled={s.sel.length === 0}
        onClick={async () => { await onDeleteSelected(s.sel); s.stop() }}>
        <Trash2 size={16} /> {deleteLabel} ({s.sel.length})
      </Key>
      <Key label="סיום בחירה" className="px-3 h-10 text-sm" onClick={s.stop}><X size={16} /> סיום</Key>
    </div>
  )
}

/** A list row that shows a checkbox in select mode and toggles on tap. */
export function SelectableRow({ s, id, children, className = '' }: { s: Selection; id: string; children: ReactNode; className?: string }) {
  const checked = s.sel.includes(id)
  return (
    <li className={`flex items-center gap-3 ${s.on ? 'cursor-pointer' : ''} ${checked ? 'bg-secondary/5' : ''} ${className}`}
      onClick={s.on ? () => s.toggle(id) : undefined}>
      {s.on && (
        <input type="checkbox" className="w-5 h-5 shrink-0" checked={checked} aria-label="בחר פריט"
          onChange={() => s.toggle(id)} onClick={(e) => e.stopPropagation()} />
      )}
      {children}
    </li>
  )
}
