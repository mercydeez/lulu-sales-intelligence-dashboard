'use client';

import { TrendingUp, Sparkles } from 'lucide-react';
import { Card, EmptyState, SkeletonCard } from '@/components/ui';
import { Promotion } from './types';
import { discountDisplay, daysRemaining, formatNumber } from './format';

interface ActivePromotionsProps {
  promotions: Promotion[];
  loading: boolean;
}

// Rotate gradient treatments so the carousel cards don't all look identical.
const GRADIENTS = ['sunset-warm', 'sunset-gradient', 'sunset-cool', 'sunset-warm'];

export function ActivePromotions({ promotions, loading }: ActivePromotionsProps) {
  const featured = promotions.slice(0, 4);

  return (
    <section className="mb-8">
      <h2 className="text-xl font-semibold text-ink mb-4 flex items-center gap-2">
        <TrendingUp className="w-5 h-5 text-coral-500" />
        Active Promotions
      </h2>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : featured.length === 0 ? (
        <Card variant="glass" padding="lg">
          <EmptyState
            icon={<Sparkles className="w-6 h-6" />}
            title="No active promotions"
            description="Nothing is running right now. Create a promotion to drive redemptions."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {featured.map((promo, index) => (
            <div
              key={promo.id}
              className={`on-sunset relative overflow-hidden rounded-2xl p-5 text-white card-pop ${GRADIENTS[index % GRADIENTS.length]}`}
            >
              <div className="relative z-10">
                <div className="flex justify-between items-start mb-3 gap-2">
                  <span className="px-2 py-1 bg-white/20 rounded-lg text-xs font-medium">
                    {promo.category || 'All Categories'}
                  </span>
                  <span className="text-xl font-bold whitespace-nowrap">{discountDisplay(promo)}</span>
                </div>
                <h3 className="font-semibold text-lg mb-1 line-clamp-1">{promo.name}</h3>
                <p className="text-white/80 text-sm mb-4 line-clamp-2 min-h-[2.5rem]">{promo.description}</p>
                <div className="flex justify-between items-center text-sm">
                  <div>
                    <p className="text-white/60">Redemptions</p>
                    <p className="font-semibold">{formatNumber(promo.redemption_count)}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-white/60">Ends in</p>
                    <p className="font-semibold">{daysRemaining(promo)} days</p>
                  </div>
                </div>
              </div>
              <div className="absolute -right-6 -bottom-6 w-24 h-24 bg-white/15 rounded-full blur-xl" />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
