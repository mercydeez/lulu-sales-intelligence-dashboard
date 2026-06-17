import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import AIProvider from '@/components/AIProvider';
import { AuthProvider } from '@/contexts/AuthContext';
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
    <html lang="en" className="light">
      <body className={`${inter.className} text-ink antialiased`}>
        <div className="min-h-screen">
          <AuthProvider>
            <AIProvider>
              <ClientLayout>
                {children}
              </ClientLayout>
            </AIProvider>
          </AuthProvider>
        </div>
      </body>
    </html>
  );
}
