import type { Metadata, Viewport } from 'next';
import { Manrope, IBM_Plex_Mono } from 'next/font/google';
import './globals.css';
import AIProvider from '@/components/AIProvider';
import { AuthProvider } from '@/contexts/AuthContext';
import { ExperienceProvider } from '@/contexts/ExperienceContext';
import { LanguageProvider } from '@/contexts/LanguageContext';
import { ThemeProvider } from '@/contexts/ThemeContext';
import { ToastProvider } from '@/components/ui/Toast';
import ClientLayout from '@/components/ClientLayout';
import ServiceWorkerRegister from '@/components/ServiceWorkerRegister';
import ChunkLoadRecovery from '@/components/ChunkLoadRecovery';
import { PRODUCT_NAME } from '@/lib/brand';

const manrope = Manrope({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
  variable: '--font-manrope',
});
const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-plex-mono',
});

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#0f766e' },
    { media: '(prefers-color-scheme: dark)', color: '#0b0d0e' },
  ],
};

const APP_TITLE = `${PRODUCT_NAME} | Real-time Retail Analytics`;
const APP_DESCRIPTION =
  'Real-time sales streaming, demand forecasting, and inventory intelligence for retail operations.';

function resolveMetadataBase() {
  const candidate = process.env.NEXT_PUBLIC_APP_URL?.trim() || 'http://localhost:3000';
  try {
    return new URL(candidate);
  } catch {
    return new URL('http://localhost:3000');
  }
}

export const metadata: Metadata = {
  title: { default: APP_TITLE, template: `%s · ${PRODUCT_NAME}` },
  description: APP_DESCRIPTION,
  metadataBase: resolveMetadataBase(),
  manifest: '/manifest.webmanifest',
  applicationName: PRODUCT_NAME,
  appleWebApp: { capable: true, title: PRODUCT_NAME, statusBarStyle: 'default' },
  icons: {
    icon: [
      { url: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: '/icons/apple-touch-icon.png',
  },
  openGraph: {
    type: 'website',
    siteName: PRODUCT_NAME,
    title: APP_TITLE,
    description: APP_DESCRIPTION,
    images: [{ url: '/icons/icon-512.png', width: 512, height: 512, alt: PRODUCT_NAME }],
  },
  twitter: {
    card: 'summary',
    title: APP_TITLE,
    description: APP_DESCRIPTION,
    images: ['/icons/icon-512.png'],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" dir="ltr" className="light" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var l=localStorage.getItem('lang');if(l==='ar'){document.documentElement.lang='ar';document.documentElement.dir='rtl';}var t=localStorage.getItem('theme');var d=t==='dark'||((t==null||t==='system')&&window.matchMedia('(prefers-color-scheme: dark)').matches);if(d){var c=document.documentElement.classList;c.remove('light');c.add('dark');}}catch(e){}})();`,
          }}
        />
      </head>
      <body className={`${manrope.variable} ${plexMono.variable} font-sans text-ink antialiased`}>
        <ServiceWorkerRegister />
        <ChunkLoadRecovery />
        <div className="min-h-screen">
          <ThemeProvider>
          <LanguageProvider>
            <AuthProvider>
              <ExperienceProvider>
              <ToastProvider>
                <AIProvider>
                  <ClientLayout>
                    {children}
                  </ClientLayout>
                </AIProvider>
              </ToastProvider>
              </ExperienceProvider>
            </AuthProvider>
          </LanguageProvider>
          </ThemeProvider>
        </div>
      </body>
    </html>
  );
}
