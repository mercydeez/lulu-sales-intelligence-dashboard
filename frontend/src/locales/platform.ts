/**
 * Locale domain: platform CX surfaces — usage meters, what's-new changelog,
 * status page (steward: Yash). AR strings are DRAFT pending native review.
 */
type Dict = Record<string, string>;

export const en: Dict = {
  'usage.title': 'Plan usage',
  'usage.advisory': 'Advisory meters for this billing period — nothing is blocked at the limit yet.',
  'usage.enforced': 'Usage limits are enforced on this plan for the current billing period.',
  'usage.unlimited': 'Unlimited',
  'usage.overQuota': 'You have passed a plan limit. Upgrade to keep full speed at month end.',
  'usage.upgrade': 'View plans',
  'whatsnew.title': "What's new",
  'whatsnew.aria': "What's new — product updates",
  'whatsnew.empty': 'No updates yet.',
  'whatsnew.viewStatus': 'System status',
  'status.title': 'System status',
  'status.description': 'Live component health, straight from the platform — no marketing layer.',
  'status.operational': 'All systems operational',
  'status.degraded': 'Partial degradation',
  'status.down': 'Service disruption',
  'status.checking': 'Checking…',
  'status.component.api': 'Core API',
  'status.component.app': 'Web application',
  'status.commitment': 'Our commitment',
  'status.incidents': 'Recent incidents',
  'status.noIncidents': 'No incidents recorded in this window.',
  'status.lastChecked': 'Last checked',
};

export const ar: Dict = {
  // DRAFT — pending native review (E4-4)
  'usage.title': 'استخدام الخطة',
  'usage.advisory': 'عدادات إرشادية لفترة الفوترة الحالية — لا يتم حظر أي شيء عند الحد بعد.',
  'usage.enforced': 'حدود الاستخدام مفعّلة على هذه الخطة لفترة الفوترة الحالية.',
  'usage.unlimited': 'غير محدود',
  'usage.overQuota': 'لقد تجاوزت حد الخطة. قم بالترقية للحفاظ على السرعة الكاملة نهاية الشهر.',
  'usage.upgrade': 'عرض الخطط',
  'whatsnew.title': 'ما الجديد',
  'whatsnew.aria': 'ما الجديد — تحديثات المنتج',
  'whatsnew.empty': 'لا تحديثات بعد.',
  'whatsnew.viewStatus': 'حالة النظام',
  'status.title': 'حالة النظام',
  'status.description': 'صحة المكونات مباشرة من المنصة — بدون طبقة تسويقية.',
  'status.operational': 'جميع الأنظمة تعمل',
  'status.degraded': 'تدهور جزئي',
  'status.down': 'انقطاع في الخدمة',
  'status.checking': 'جارٍ الفحص…',
  'status.component.api': 'الواجهة البرمجية الأساسية',
  'status.component.app': 'تطبيق الويب',
  'status.commitment': 'التزامنا',
  'status.incidents': 'الحوادث الأخيرة',
  'status.noIncidents': 'لا حوادث مسجلة في هذه الفترة.',
  'status.lastChecked': 'آخر فحص',
};
