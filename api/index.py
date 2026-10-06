import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app as flask_app


class VercelWSGIMiddleware:
    """
    Vercel rewrites forward all traffic to /api/index.py, setting PATH_INFO to '/api/index.py'.
    This middleware restores the original client request path (e.g. '/api/triage', '/')
    from Vercel's HTTP_X_MATCHED_PATH or HTTP_X_FORWARDED_URI headers so Flask's URL router
    can accurately distinguish between index.html and API endpoints.
    """
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        matched_path = environ.get('HTTP_X_MATCHED_PATH') or environ.get('HTTP_X_FORWARDED_URI')

        if matched_path:
            clean_path = matched_path.split('?')[0]
            if not clean_path.startswith('/api/index.py'):
                environ['PATH_INFO'] = clean_path
                if '?' in matched_path and not environ.get('QUERY_STRING'):
                    environ['QUERY_STRING'] = matched_path.split('?', 1)[1]
            else:
                environ['PATH_INFO'] = '/'
        elif environ.get('PATH_INFO') in ('/api/index.py', '/api/index'):
            environ['PATH_INFO'] = '/'

        return self.application(environ, start_response)


app = VercelWSGIMiddleware(flask_app)
