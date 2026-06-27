import type { Metadata, Viewport } from 'next';
import { Manrope, IBM_Plex_Mono } from 'next/font/google';
import './globals.css';
import AIProvider from '@/components/AIProvider';
import { AuthProvider } from '@/contexts/AuthContext';
import { LanguageProvider } from '@/contexts/LanguageContext';
import { ToastProvider } from '@/components/ui/Toast';
import ClientLayout from '@/components/ClientLayout';
import ServiceWorkerRegister from '@/components/ServiceWorkerRegister';
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
  // Brand teal tints the mobile browser / PWA chrome.
  themeColor: '#0f766e',
};

const APP_TITLE = `${PRODUCT_NAME} | Real-time Retail Analytics`;
const APP_DESCRIPTION =
  'Real-time sales streaming, demand forecasting, and inventory intelligence for retail operations.';

export const metadata: Metadata = {
  title: { default: APP_TITLE, template: `%s · ${PRODUCT_NAME}` },
  description: APP_DESCRIPTION,
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
        {/* Set language + direction before first paint to avoid an EN/AR flash
            and the "English text with an RTL sidebar" mismatch. Kept in sync at
            runtime by LanguageContext. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var l=localStorage.getItem('lang');if(l==='ar'){document.documentElement.lang='ar';document.documentElement.dir='rtl';}}catch(e){}})();`,
          }}
        />
      </head>
      <body className={`${manrope.variable} ${plexMono.variable} font-sans text-ink antialiased`}>
        <ServiceWorkerRegister />
        <div className="min-h-screen">
          <LanguageProvider>
            <AuthProvider>
              <ToastProvider>
                <AIProvider>
                  <ClientLayout>
                    {children}
                  </ClientLayout>
                </AIProvider>
              </ToastProvider>
            </AuthProvider>
          </LanguageProvider>
        </div>
      </body>
    </html>
  );
}
