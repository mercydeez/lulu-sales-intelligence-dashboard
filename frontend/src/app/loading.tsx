import { Loader2 } from 'lucide-react';
import { PRODUCT_NAME } from '@/lib/brand';

export default function Loading() {
  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center gap-4 text-center">
      <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl sunset-gradient text-white shadow-sunset">
        <Loader2 className="w-7 h-7 animate-spin" />
      </div>
      <p className="text-sm font-medium text-ink-muted">Loading {PRODUCT_NAME}…</p>
    </div>
  );
}
