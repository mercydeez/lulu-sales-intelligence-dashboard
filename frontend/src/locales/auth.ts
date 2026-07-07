/**
 * Locale domain: auth screens — login, 2FA, forgot password (steward: Yash).
 * Full-Arabic coverage for the login screen (E4-4 core screen #5).
 *
 * AR strings are DRAFT translations pending native-speaker review (E4-4's
 * translator step) — flag review comments here rather than editing piecemeal.
 */
type Dict = Record<string, string>;

export const en: Dict = {
  'auth.badge': 'Real-time retail analytics',
  'auth.heroTitle': 'Every sale, every store, the moment it happens.',
  'auth.heroSub':
    'Live KPIs, demand forecasting, and inventory intelligence across the Meridian Hypermarket UAE network — in one immersive, powerful workspace.',
  'auth.feature.live': 'Live sales stream updating every few seconds',
  'auth.feature.forecast': 'Seasonal demand forecasts with accuracy scoring',
  'auth.feature.rbac': 'Role-based access scoped to your stores',
  'auth.footnote': 'Independent student project · synthetic data · © 2026 Meridian Hypermarket UAE',
  'auth.tagline': 'UAE Sales Analytics Dashboard',
  'auth.welcome': 'Welcome back 👋',
  'auth.signInSub': 'Sign in to your analytics workspace.',
  'auth.email': 'Email Address',
  'auth.password': 'Password',
  'auth.rememberMe': 'Remember me',
  'auth.forgot': 'Forgot password?',
  'auth.signIn': 'Sign In',
  'auth.signingIn': 'Signing in...',
  'auth.verify': 'Verify',
  'auth.verifying': 'Verifying...',
  'auth.backToSignIn': 'Back to sign in',
  'auth.mfaNotice': 'Two-step verification is on. Enter the 6-digit code from your authenticator app.',
  'auth.authCode': 'Authentication code',
  'auth.tryDemo': 'Try a demo account',
  'auth.demoPassword': 'Password for all demos:',
  'auth.newHere': 'New here?',
  'auth.createWorkspace': 'Create your workspace',
  'auth.demo.superAdmin': 'Super Admin',
  'auth.demo.regional': 'Regional Mgr',
  'auth.demo.store': 'Store Mgr',
  'auth.errBoth': 'Please enter both email and password',
  'auth.errCode': 'Enter the 6-digit code from your authenticator app',
  'auth.errForgotNeedsEmail': 'Enter your email above, then click “Forgot password?”',
  'auth.forgotSent': 'If that account exists, a password reset link has been sent.',
};

export const ar: Dict = {
  // DRAFT — pending native review (E4-4)
  'auth.badge': 'تحليلات البيع بالتجزئة الفورية',
  'auth.heroTitle': 'كل عملية بيع، في كل متجر، لحظة حدوثها.',
  'auth.heroSub':
    'مؤشرات أداء مباشرة، وتنبؤ بالطلب، وذكاء المخزون عبر شبكة ميريديان هايبرماركت الإمارات — في مساحة عمل واحدة قوية وغامرة.',
  'auth.feature.live': 'بث مباشر للمبيعات يتحدّث كل بضع ثوانٍ',
  'auth.feature.forecast': 'تنبؤات موسمية بالطلب مع تقييم الدقة',
  'auth.feature.rbac': 'وصول حسب الدور مقيّد بمتاجرك',
  'auth.footnote': 'مشروع طلابي مستقل · بيانات اصطناعية · © 2026 ميريديان هايبرماركت الإمارات',
  'auth.tagline': 'لوحة تحليلات المبيعات في الإمارات',
  'auth.welcome': 'أهلاً بعودتك 👋',
  'auth.signInSub': 'سجّل الدخول إلى مساحة التحليلات الخاصة بك.',
  'auth.email': 'البريد الإلكتروني',
  'auth.password': 'كلمة المرور',
  'auth.rememberMe': 'تذكرني',
  'auth.forgot': 'نسيت كلمة المرور؟',
  'auth.signIn': 'تسجيل الدخول',
  'auth.signingIn': 'جارٍ تسجيل الدخول...',
  'auth.verify': 'تحقق',
  'auth.verifying': 'جارٍ التحقق...',
  'auth.backToSignIn': 'العودة إلى تسجيل الدخول',
  'auth.mfaNotice': 'التحقق بخطوتين مفعّل. أدخل الرمز المكوَّن من 6 أرقام من تطبيق المصادقة.',
  'auth.authCode': 'رمز المصادقة',
  'auth.tryDemo': 'جرّب حساباً تجريبياً',
  'auth.demoPassword': 'كلمة المرور لجميع الحسابات التجريبية:',
  'auth.newHere': 'جديد هنا؟',
  'auth.createWorkspace': 'أنشئ مساحة عملك',
  'auth.demo.superAdmin': 'مشرف عام',
  'auth.demo.regional': 'مدير إقليمي',
  'auth.demo.store': 'مدير متجر',
  'auth.errBoth': 'يرجى إدخال البريد الإلكتروني وكلمة المرور',
  'auth.errCode': 'أدخل الرمز المكوَّن من 6 أرقام من تطبيق المصادقة',
  'auth.errForgotNeedsEmail': 'أدخل بريدك الإلكتروني أعلاه ثم اضغط «نسيت كلمة المرور؟»',
  'auth.forgotSent': 'إذا كان الحساب موجوداً، فقد أُرسل رابط إعادة تعيين كلمة المرور.',
};
