from django.conf import settings
from redis import StrictRedis

redis = StrictRedis(**getattr(settings, 'STASTE_REDIS_CONNECTION', {}))

if not getattr(settings, 'STASTE_METRICS_PREFIX', None):
    settings.STASTE_METRICS_PREFIX = 'staste'

key_naming = getattr(settings, 'STASTE_KEY_NAMING', {})
ALL = key_naming.get('all', '__all__')
CHOICES = key_naming.get('choices', '__choices__')