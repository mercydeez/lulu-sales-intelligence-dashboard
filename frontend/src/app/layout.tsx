import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import AIProvider from '@/components/AIProvider';
import { AuthProvider } from '@/contexts/AuthContext';
import { LanguageProvider } from '@/contexts/LanguageContext';
import ClientLayout from '@/components/ClientLayout';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const viewport: Viewport = {
  themeColor: '#fdf6f3',
};

export const metadata: Metadata = {
  title: 'Lulu Hypermarket Sales Dashboard | Real-time Analytics',
  description: 'Real-time sales streaming and analytics dashboard for Lulu Hypermarket UAE',
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
      <body className={`${inter.variable} font-sans text-ink antialiased`}>
        <div className="min-h-screen">
          <LanguageProvider>
            <AuthProvider>
              <AIProvider>
                <ClientLayout>
                  {children}
                </ClientLayout>
              </AIProvider>
            </AuthProvider>
          </LanguageProvider>
        </div>
      </body>
    </html>
  );
}
