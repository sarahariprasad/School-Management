import os
environment = os.getenv("DJANGO_ENV", "development").lower()
if environment == "production":
    from .settings_production import *  # noqa: F403
else:
    from .settings_development import *  # noqa: F403
