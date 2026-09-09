from os.path import dirname, join


def _installed_apps():
    """Explicit ZeroConfig; add KernelConfig only when the companion split exists.

    Current django-trusts master (post #45, pre Step 3 kernel PR) still
    ships ``trusts.apps.AppConfig`` with ``label='trusts'``. Installing
    that alongside Zero would collide. After the kernel PR, KernelConfig
    uses ``label='trusts_kernel'`` and must be listed first.
    """
    apps = [
        'django.contrib.admin',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.messages',
        'django.contrib.staticfiles',
        'trusts.zero.apps.ZeroConfig',
        'tests.apps.TestsConfig',
    ]
    try:
        from trusts.apps import KernelConfig
    except ImportError:
        return tuple(apps)
    if (
        getattr(KernelConfig, 'name', None) == 'trusts'
        and getattr(KernelConfig, 'label', None) == 'trusts_kernel'
    ):
        idx = apps.index('trusts.zero.apps.ZeroConfig')
        apps.insert(idx, 'trusts.apps.KernelConfig')
    return tuple(apps)


SECRET_KEY = '01)%8q7ub=+yw7^#dz5s!6kkff6%al5f)_ayvep9_b&w1q-dvs'

USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
LOGIN_URL = '/accounts/login/'
STATIC_URL = '/static/'
ALLOWED_HOSTS = ['beedesk.com', 'testserver', 'localhost']
# Junction docs still describe content = ForeignKey(..., unique=True).
SILENCED_SYSTEM_CHECKS = ['fields.W342']

INSTALLED_APPS = _installed_apps()

AUTHENTICATION_BACKENDS = (
    'trusts.zero.backends.TrustModelBackend',
)

MIDDLEWARE = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
)

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'DIRS': [
            join(dirname(__file__), 'templates'),
        ],
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

ROOT_URLCONF = 'tests.urls'
