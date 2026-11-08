import './globals.css';
import type { Metadata, Viewport } from 'next';
import { Toasts } from '@/components/toast';
import { SWRegister } from '@/components/SWRegister';

export const metadata: Metadata = {
  title: 'Law & Justice CRM',
  description: 'CRM юридической компании Law & Justice',
  manifest: '/manifest.json',
  icons: { icon: '/icon.svg', apple: '/icon.svg' },
  appleWebApp: { capable: true, title: 'L&J CRM', statusBarStyle: 'default' },
};
export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#2A47A1' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ru" data-sidebar={process.env.NEXT_PUBLIC_SIDEBAR === 'brand' ? 'brand' : 'light'}>
    <head>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
      {/* eslint-disable-next-line @next/next/no-page-custom-font */}
      <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
    </head>
    <body>{children}<Toasts /><SWRegister /></body>
  </html>;
}
