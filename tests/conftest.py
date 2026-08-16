# tests/conftest.py
#
# Note on test isolation and get_settings()
# -----------------------------------------
# get_settings() is decorated with @lru_cache, which means the first call
# wins for the lifetime of the process. Tests that need different settings
# patch get_settings at the point of use (e.g. app.routes.messages.get_settings)
# rather than clearing the cache.
#
# The CORS tests (test_cors.py) construct a fresh app via _create_app() inside
# the patch context rather than using the module-level `app` singleton. This is
# necessary because CORS middleware is applied during app construction, not at
# request time. The trade-off is that _create_app() tests exercise a different
# instance than the production singleton — if startup logic ever depends on
# module-level state that is set before _create_app() runs, that gap could hide
# bugs.
#
# If that becomes a concern, replace the _create_app() approach with:
#
#   @pytest.fixture(autouse=True, scope="session")
#   def clear_settings_cache():
#       from app.config import get_settings
#       get_settings.cache_clear()
#       yield
#       get_settings.cache_clear()
#
# and patch the singleton app directly. For now the _create_app() approach is
# simpler and sufficient.
