/**
 * Per-domain locale registry (E4-4 i18n split — steward: Yash).
 *
 * Each domain module exports `en` and `ar` dicts under its own namespace
 * prefix; this index merges them into the two flat dictionaries that
 * LanguageContext serves via `t()`. Adding a domain = one import + one line
 * per merge — owners never edit each other's files (replaces the old
 * append-to-one-giant-file rule).
 */
import * as nav from './nav';
import * as operations from './operations';
import * as commercial from './commercial';
import * as auth from './auth';
import * as ai from './ai';
import * as platform from './platform';

type Dict = Record<string, string>;

export const en: Dict = {
  ...nav.en,
  ...operations.en,
  ...commercial.en,
  ...auth.en,
  ...ai.en,
  ...platform.en,
};

export const ar: Dict = {
  ...nav.ar,
  ...operations.ar,
  ...commercial.ar,
  ...auth.ar,
  ...ai.ar,
  ...platform.ar,
};
