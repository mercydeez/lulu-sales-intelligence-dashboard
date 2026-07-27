/**
 * Locale domain: home / inventory / alerts headings (steward: Yash).
 * EN/AR + RTL shell pass — data values stay untranslated.
 */
type Dict = Record<string, string>;

export const en: Dict = {
  'home.executiveInsights': 'Executive Insights',
  'home.realTimeStream': 'Real-Time Stream',
  'home.filteredRegion': '(Filtered to your region)',
  'home.filteredStore': '(Filtered to your store)',
  'inventory.title': 'Inventory & Procurement',
  'inventory.description': 'Monitor stock levels, manage alerts, and handle procurement across all stores',
  'inventory.tab.inventory': 'Inventory',
  'inventory.tab.alerts': 'Alerts',
  'inventory.tab.procurement': 'Procurement',
  'alerts.title': 'Alerts & Tasks',
  'alerts.description': 'Monitor, acknowledge, and resolve operational alerts across all stores',
  'alerts.tab.all': 'All Alerts',
  'alerts.tab.tasks': 'My Tasks',
};

export const ar: Dict = {
  'home.executiveInsights': 'رؤى تنفيذية',
  'home.realTimeStream': 'البث الفوري',
  'home.filteredRegion': '(مُصفّى حسب منطقتك)',
  'home.filteredStore': '(مُصفّى حسب متجرك)',
  'inventory.title': 'المخزون والمشتريات',
  'inventory.description': 'راقب مستويات المخزون وأدِر التنبيهات وتعامل مع المشتريات عبر جميع المتاجر',
  'inventory.tab.inventory': 'المخزون',
  'inventory.tab.alerts': 'التنبيهات',
  'inventory.tab.procurement': 'المشتريات',
  'alerts.title': 'التنبيهات والمهام',
  'alerts.description': 'راقب التنبيهات التشغيلية وأقرّها وحلّها عبر جميع المتاجر',
  'alerts.tab.all': 'جميع التنبيهات',
  'alerts.tab.tasks': 'مهامي',
};
