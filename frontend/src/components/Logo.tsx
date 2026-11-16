/** Знак Law & Justice: щит с весами (по логотипу lexandjustice.com). Цвет — currentColor. */
export function LogoMark({ className = 'logo' }: { className?: string }) {
  return <svg className={className} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M16 2.8 26.5 6.4v8.2c0 6.6-4.4 11.6-10.5 14-6.1-2.4-10.5-7.4-10.5-14V6.4z" />
    <path d="M16 8.2v15.6M11 11.2h10M12.6 23.8h6.8" />
    <path d="M11 11.2 8.4 17h5.2zM21 11.2 18.4 17h5.2z" />
    <path d="M8.4 17a2.6 2.6 0 0 0 5.2 0M18.4 17a2.6 2.6 0 0 0 5.2 0" />
    <circle cx="16" cy="7.4" r="1" fill="currentColor" stroke="none" />
  </svg>;
}
