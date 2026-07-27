/**
 * Locale domain: AI / experience screens — insights, briefing, value
 * (owner: Atharva; mechanism stewarded by Yash).
 *
 * STAGED for E4-4: these keys cover the page headers of three of the five
 * core-Arabic screens. Wiring `t()` into the page JSX is Atharva's to apply
 * (his bounded context) — the dictionaries are ready so that wiring needs no
 * dict work. AR strings are DRAFT pending native review.
 */
type Dict = Record<string, string>;

export const en: Dict = {
  'insights.title': 'Insights',
  'insights.description': 'Grounded findings from the diagnostics engine — with the numbers behind them',
  'briefing.title': 'Executive Briefing',
  'briefing.description': 'What changed, why, and what to do about it',
  'value.title': 'Value',
  'value.description': 'Realized savings and measured outcomes from accepted decisions',
};

export const ar: Dict = {
  // DRAFT — pending native review (E4-4)
  'insights.title': 'الرؤى',
  'insights.description': 'نتائج مؤسسة على البيانات من محرك التشخيص — مع الأرقام التي تدعمها',
  'briefing.title': 'الموجز التنفيذي',
  'briefing.description': 'ما الذي تغيّر، ولماذا، وما الإجراء المناسب',
  'value.title': 'القيمة',
  'value.description': 'الوفورات المحققة والنتائج المقاسة من القرارات المعتمدة',
};
