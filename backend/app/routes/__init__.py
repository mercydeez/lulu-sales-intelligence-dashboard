"""Route modules — mounted via app.routes.registry (see ROUTERS there).

Deliberately empty of imports: eagerly importing route modules here forced an
import order (importing ANY route pulled in five others) and made the package
__init__ a hidden coupling point. Import route modules directly.
"""
