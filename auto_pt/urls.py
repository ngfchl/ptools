from django.urls import path

from auto_pt import views

urlpatterns = [
    path(r'get_tasks', views.get_tasks, name='get_tasks'),
    path(r'add_task', views.get_tasks, name='add_task'),
    path(r'exec_task', views.exec_task, name='exec_task'),
    path(r'test_field', views.test_field, name='test_field'),
    path(r'test_notify', views.test_notify, name='test_notify'),
    path(r'update', views.update_page, name='update_page'),
    path(r'do_restart', views.do_restart, name='do_restart'),
    path(r'do_update', views.do_update, name='do_update'),
    path(r'do_xpath', views.do_xpath, name='do_xpath'),
    path(r'import_from_ptpp', views.import_from_ptpp, name='import_from_ptpp'),
    path(r'page_downloading', views.page_downloading, name='page_downloading'),
    path(r'get_downloaders', views.get_downloaders, name='get_downloaders'),
    path(r'get_downloader_categories', views.get_downloader_categories, name='get_downloader_categories'),
    path(r'get_trackers', views.get_trackers, name='get_trackers'),
    path(r'downloading', views.get_downloading, name='downloading'),
    path(r'control_torrent', views.control_torrent, name='control_torrent'),
    path(r'torrent_info_page', views.render_torrents_page, name='torrent_info_page'),
    path(r'get_torrent_info_list', views.get_torrent_info_list, name='get_torrent_info_list'),
    path(r'site_status_api', views.site_status_api, name='site_status_api'),
    path(r'site_status', views.site_status, name='site_status'),
    path(r'site_data_api', views.site_data_api, name='site_data_api'),
    path(r'downloading_status', views.downloading_status, name='downloading_status'),
    path(r'do_sql', views.do_sql, name='do_sql'),
]
