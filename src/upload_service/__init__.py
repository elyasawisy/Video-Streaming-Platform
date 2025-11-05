"""Upload service package.

This package intentionally avoids importing the Flask `app` at package
import time to prevent side-effects (database connections, table creation)
when other services import models. Import `upload_service.app` explicitly
where the Flask app is required.
"""

__all__ = []

