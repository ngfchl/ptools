"""
Django settings for djangoProject project.

Generated by 'django-admin startproject' using Django 4.0.6.

For more information on this file, see
https://docs.djangoproject.com/en/4.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.0/ref/settings/
"""
import datetime
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-6wrh^t$@gbb^s^=79@%cv=%yhq6gl^kane#g@-n-*n6+s1lo2f'

# SECURITY WARNING: don't run with debug turned on in production!
# SECURITY WARNING: don't run with debug turned on in production!
# if os.environ.get('DJANGO_DEBUG'):
#     print("Debug is enabled.")
#     DEBUG = True
#     # When not specified, ALLOW_HOSTS defaults to:
#     # ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
# else:
#     DEBUG = False
DEBUG = True

ALLOWED_HOSTS = ['*']
CORS_ORIGIN_ALLOW_ALL = True
if os.environ.get('HTTPS_DOMAINS'):
    CSRF_TRUSTED_ORIGINS = [os.environ.get('HTTPS_DOMAINS'), ]

# Application definition

INSTALLED_APPS = [
    'simpleui',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'django_apscheduler',
    'django_admin_inline_paginator',
    'util',
    'util.templatetags',
    'pt_site',
    'pt_test',
    'auto_pt',
]

MIDDLEWARE = [
    # 'django.middleware.cache.UpdateCacheMiddleware',  # redis1
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # 'django.middleware.cache.FetchFromCacheMiddleware',  # redis2

]

ROOT_URLCONF = 'ptools.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ptools.wsgi.application'

# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db/db.sqlite3',
        'OPTIONS': {
            'timeout': 120,
            'check_same_thread': False
        }
    },
    # 'default': {
    #     'ENGINE': 'django.db.backends.mysql',  # 数据库引擎
    #     'NAME': 'pt',  # 数据库名，先前创建的
    #     'USER': 'pt',  # 用户名，可以自己创建用户
    #     'PASSWORD': 'bfmAjPysaFkmWsfs',  # 密码
    #     'HOST': 'docker_db_1',  # mysql服务所在的主机ip
    #     'PORT': '3306',  # mysql服务端口
    # },
    # 'default': {
    #     'ENGINE': 'django.db.backends.mysql',  # 数据库引擎
    #     'NAME': 'pt',  # 数据库名，先前创建的
    #     'USER': 'pt',  # 用户名，可以自己创建用户
    #     'PASSWORD': 'bfmAjPysaFkmWsfs',  # 密码
    #     'HOST': 'bt.9oho.cn',  # mysql服务所在的主机ip
    #     'PORT': '3306',  # mysql服务端口
    # }
}
"""
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        # 'LOCATION': "redis://127.0.0.1:6333",
        'LOCATION': "redis://127.0.0.1:6379/0",
        'TIMEOUT': 200,  # NONE 永不超时
        'OPTIONS': {
            # "PASSWORD": "",  # 密码，没有可不设置
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',  # redis-py 客户端
            'PICKLE_VERSION': -1,  # 插件使用PICKLE进行序列化,-1表示最新版本
            'CONNECTION_POOL_KWARGS': {"max_connections": 100},  # 连接池最大连接数
            'SOCKET_CONNECT_TIMEOUT': 5,  # 连接超时
            'SOCKET_TIMEOUT': 5,  # 读写超时
        }
        # "KEY_PREFIX ":"test",#前缀
    }
}
"""
# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
LOGGING = {
    'version': 1,  # 版本
    'disable_existing_loggers': False,  # 是否禁用已经存在的日志器
    'formatters': {  # 日志信息显示的格式
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(lineno)d %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(module)s %(lineno)d %(message)s'
        },
    },
    'filters': {  # 过滤器
        'require_debug_true': {  # django在debug模式下才输出日志
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {  # 日志处理方法
        'console': {  # 向终端中输出日志
            'level': 'DEBUG',  # 输出等级为“INFO”
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
        'file': {  # 向文件中输出日志
            'level': 'DEBUG',  # 输出等级为“INFO”
            # 新增内容
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'db/logs.log'),
            'when': 'midnight',
            'backupCount': 30,
            # 'class': 'logging.handlers.RotatingFileHandler',
            # 'filename': "db/{}.log".format(datetime.datetime.today()),  # 日志文件的位置
            # 'maxBytes': 30 * 1024 * 1024,  # 日志文件的大小（300*1024*1024为300MB）
            # 'backupCount': 10,  # 日志文件的数量（超过设定的最大值会自动备份，备份数量最大值为10）
            'formatter': 'verbose'  # 日志输出格式：使用了在之前定义的'verbose'
        },
    },
    'loggers': {  # 日志器
        'ptools': {  # 定义了一个名为django的日志器
            'handlers': ['console', 'file'],  # 可以同时向终端与文件中输出日志
            'propagate': True,  # 是否继续传递日志信息
            'level': 'DEBUG',  # 日志器接收的最低日志级别
        },
    }
}

# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'zh-Hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_TZ = False

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = 'static/'
# STATIC_ROOT = os.path.join(BASE_DIR, 'static')
STATICFILES_DIRS = (
    os.path.join(os.path.join(BASE_DIR, 'static')),
)
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
# DATA_UPLOAD_MAX_MEMORY_SIZE：这个设置翻译过来就是：数据上传最大内存大小
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760
APSCHEDULER_DATETIME_FORMAT = 'Y-m-d H:i:s'  # Default
APSCHEDULER_RUN_NOW_TIMEOUT = 300  # 任务执行超时时间
# 自定义配置
SIMPLEUI_HOME_TITLE = 'PT一下你就知道'
SIMPLEUI_HOME_ICON = 'fa fa-optin-monster'
SIMPLEUI_HOME_INFO = False
SIMPLEUI_LOGO = '/static/logo1.png'
SIMPLEUI_INDEX = '/tasks/restart'
# SIMPLEUI配置
SIMPLEUI_CONFIG = {
    'system_keep': True,
    # 'menu_display': ['下载管理', ],  # 开启排序和过滤功能, 不填此字段为默认排序和全部显示, 空列表[] 为全部不显示.
    'dynamic': True,  # 设置是否开启动态菜单, 默认为False. 如果开启, 则会在每次用户登陆时动态展示菜单内容
    'menus': [{
        'app': 'downloader',
        'name': '下载管理',
        'icon': 'fas fa-user-shield',
        'models': [{
            'name': '任务管理',
            'icon': 'fa fa-user',
            'url': '/tasks/page_downloading'
        }, {
            'name': '查询种子',
            'icon': 'fa fa-user',
            'url': '/downloader/ptspider/index'
        }]
    }, {
        'app': 'update',
        'name': '更新&导入',
        'icon': 'el-icon-attract',
        'models': [{
            'name': '代码更新',
            'icon': 'el-icon-refresh',
            'url': '/tasks/update'
        }, {
            'name': '站点导入',
            'icon': 'el-icon-s-open',
            'url': '/tasks/import_from_ptpp'
        }, ]
    }]
}
