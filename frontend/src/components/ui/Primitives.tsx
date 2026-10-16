import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useApp } from '../../app/store'
import type { CapabilityState } from '../../types'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`glass p-4 sm:p-5 min-w-0 ${className}`}>{children}</section>
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3">
      <h2 className="text-lg font-bold">{children}</h2>
      {hint && <p className="text-sm text-muted mt-0.5">{hint}</p>}
    </div>
  )
}

interface KeyProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'primary' | 'danger'
  /** Accessible name; required because most keys are icon-only. */
  label: string
}
export function Key({ variant = 'default', label, className = '', children, ...rest }: KeyProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={rest.disabled ? `${label} — לא זמין` : label}
      className={`key ${variant === 'default' ? '' : variant} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}

export function CapChip({ state }: { state?: CapabilityState }) {
  const s = state ?? 'unknown'
  const map = { supported: ['ok', 'נתמך'], unsupported: ['bad', 'לא נתמך'], unknown: ['', 'לא נבדק'] } as const
  return <span className={`chip ${map[s][0]}`}>{map[s][1]}</span>
}

export function Toasts() {
  const { toasts, dismissToast } = useApp()
  const color = { success: 'ok', error: 'bad', demo: 'demo', info: '' } as const
  return (
    <div
      aria-live="polite"
      className="fixed inset-x-0 z-50 flex flex-col items-center gap-2 px-4 pointer-events-none"
      style={{ bottom: 'calc(var(--nav-h) + var(--safe-b) + 14px)' }}
    >
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.button
            key={t.id}
            initial={{ opacity: 0, y: 14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => dismissToast(t.id)}
            className={`glass chip ${color[t.kind]} pointer-events-auto !rounded-2xl !text-sm !py-2.5 !px-4 max-w-md`}
          >
            {t.text}
          </motion.button>
        ))}
      </AnimatePresence>
    </div>
  )
}
