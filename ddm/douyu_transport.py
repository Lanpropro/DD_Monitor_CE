"""TLS cipher compatibility for the exact Douyu edge origin, retaining certificate checks."""
import ssl
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter


class EdgeTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        ciphers = ':'.join(row['name'] for row in context.get_ciphers())
        context.set_ciphers(ciphers + ':AES256-GCM-SHA384')
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        kwargs['ssl_context'] = self.poolmanager.connection_pool_kw['ssl_context']
        return super().proxy_manager_for(proxy, **kwargs)


def session_for(source):
    session = requests.Session()
    parts = urlsplit(source)
    if parts.scheme == 'https' and (parts.hostname or '').endswith('.edgesrv.com'):
        session.mount(f'https://{parts.netloc}/', EdgeTLSAdapter())
    return session
