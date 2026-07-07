/**
 * Locale domain: UAE SaaS commercial control plane — settings, billing, audit,
 * tenant console (Track 7). Steward: Yash (rendering); content seams with
 * Krishna's commercial services.
 */
type Dict = Record<string, string>;

export const en: Dict = {
  'settings.company.title': 'Company profile (UAE)',
  'settings.company.description': 'Legal, tax and billing details used on invoices and for enterprise procurement.',
  'billing.title': 'Billing',
  'billing.description': 'Subscription, invoices and VAT (AED).',
  'audit.title': 'Audit log',
  'audit.description': 'Sensitive, legitimate actions across your tenant — lifecycle, billing, access, exports. PDPL evidence.',
  'tenants.console.title': 'Tenant console',
  'tenants.console.description': 'Platform operator — lifecycle state, transitions, and support notes.',
  'settings.notifications': 'Notifications',
  'settings.company': 'Company',
  'settings.billing': 'Billing & invoices',
  // Appearance (E4-2)
  'settings.appearance': 'Appearance',
  'settings.appearance.note': "System follows your device's appearance and updates automatically when it changes.",
  'theme.light': 'Light',
  'theme.dark': 'Dark',
  'theme.system': 'System',
  'theme.light.hint': 'Bright, warm console',
  'theme.dark.hint': 'Near-black, low glare',
  'theme.system.hint': 'Follows your device',
};

export const ar: Dict = {
  'settings.company.title': 'ملف الشركة (الإمارات)',
  'settings.company.description': 'التفاصيل القانونية والضريبية وبيانات الفوترة المستخدمة في الفواتير والمشتريات المؤسسية.',
  'billing.title': 'الفوترة',
  'billing.description': 'الاشتراك والفواتير وضريبة القيمة المضافة (درهم).',
  'audit.title': 'سجل التدقيق',
  'audit.description': 'الإجراءات الحساسة المشروعة عبر مؤسستك — دورة الحياة والفوترة والوصول والتصدير. دليل قانون حماية البيانات.',
  'tenants.console.title': 'وحدة تحكم المستأجرين',
  'tenants.console.description': 'مشغّل المنصة — حالة دورة الحياة والانتقالات وملاحظات الدعم.',
  'settings.notifications': 'الإشعارات',
  'settings.company': 'الشركة',
  'settings.billing': 'الفوترة والفواتير',
  // Appearance (E4-2) — draft AR, pending native review
  'settings.appearance': 'المظهر',
  'settings.appearance.note': 'يتبع خيار «النظام» مظهر جهازك ويتحدّث تلقائياً عند تغيّره.',
  'theme.light': 'فاتح',
  'theme.dark': 'داكن',
  'theme.system': 'النظام',
  'theme.light.hint': 'واجهة مضيئة دافئة',
  'theme.dark.hint': 'داكنة، منخفضة الوهج',
  'theme.system.hint': 'يتبع جهازك',
};
