import contextlib
import json
import logging
import random
import re
import ssl
import threading
import time
import traceback
from _ssl import CERT_NONE
from datetime import datetime
from urllib.request import urlopen

import aip
import cloudscraper
import dateutil.parser
import opencc
import qbittorrentapi
import requests
import transmission_rpc
import urllib3.util.ssl_
from django.db.models import QuerySet
from lxml import etree
from pypushdeer import PushDeer
from requests import Response, ReadTimeout
from urllib3.exceptions import NewConnectionError
from wechat_push import WechatPush
from wxpusher import WxPusher

from auto_pt.models import Notify, OCR
from pt_site.models import MySite, SignIn, TorrentInfo, SiteStatus, Site
from ptools.base import TorrentBaseInfo, PushConfig, CommonResponse, StatusCodeEnum, DownloaderCategory

urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL'


def cookie2dict(source_str: str):
    """
    cookies字符串转为字典格式,传入参数必须为cookies字符串
    """
    dist_dict = {}
    list_mid = source_str.split(';')
    for i in list_mid:
        # 以第一个选中的字符分割1次，
        list2 = i.split('=', 1)
        dist_dict[list2[0]] = list2[1]
    return dist_dict


# 获取字符串中的小数
get_decimals = lambda x: re.search("\d+(\.\d+)?", x).group() if re.search("\d+(\.\d+)?", x) else 0

converter = opencc.OpenCC('t2s.json')

lock = threading.Lock()

logger = logging.getLogger('ptools')


class FileSizeConvert:
    """文件大小和字节数互转"""

    @staticmethod
    def parse_2_byte(file_size: str):
        if not file_size:
            return 0
        """将文件大小字符串解析为字节"""
        regex = re.compile(r'(\d+(?:\.\d+)?)\s*([kmgtp]?b)', re.IGNORECASE)

        order = ['b', 'kb', 'mb', 'gb', 'tb', 'pb', 'eb']

        for value, unit in regex.findall(file_size):
            return int(float(value) * (1024 ** order.index(unit.lower())))

    @staticmethod
    def parse_2_file_size(byte: int):
        if not byte:
            return '0B'
        units = ["B", "KB", "MB", "GB", "TB", "PB", 'EB']
        size = 1024.0
        for i in range(len(units)):
            if (byte / size) < 1:
                return "%.3f %s" % (byte, units[i])
            byte = byte / size


class MessageTemplate:
    """消息模板"""

    status_message_template = "{} 等级：{} 魔力：{} 时魔：{} 积分：{} 分享率：{} " \
                              "做种量：{} 上传量：{} 下载量：{} 上传数：{} 下载数：{} " \
                              "邀请：{} H&R：{}\n"


class PtSpider:
    """爬虫"""

    def __init__(self, browser='chrome', platform='darwin', *args, **kwargs):
        self.browser = browser
        self.platform = platform

    @staticmethod
    def cookies2dict(source_str: str):
        """解析cookie"""
        dist_dict = {}
        list_mid = source_str.split(';')
        for i in list_mid:
            # 以第一个选中的字符分割1次，
            list2 = i.split('=', 1)
            # logger.info(list2)
            if list2[0] == '':
                continue
            dist_dict[list2[0]] = list2[1]
        return dist_dict

    def get_scraper(self, delay=0):
        return cloudscraper.create_scraper(browser={
            'browser': self.browser,
            'platform': self.platform,
            'mobile': False
        }, delay=delay)

    def send_text(self, text: str, url: str = None):
        """通知分流"""
        notifies = Notify.objects.filter(enable=True).all()
        res = '你还没有配置通知参数哦！'
        if len(notifies) <= 0:
            return res
        try:
            for notify in notifies:
                if notify.name == PushConfig.wechat_work_push:
                    """企业微信通知"""
                    notify_push = WechatPush(
                        corp_id=notify.corpid,
                        secret=notify.corpsecret,
                        agent_id=notify.agentid, )
                    res = notify_push.send_text(
                        text=text,
                        to_uid=notify.touser if notify.touser else '@all'
                    )
                    msg = '企业微信通知：{}'.format(res)
                    logger.info(msg)

                if notify.name == PushConfig.wxpusher_push:
                    """WxPusher通知"""
                    res = WxPusher.send_message(
                        content=text,
                        url=url,
                        uids=notify.touser.split(','),
                        token=notify.corpsecret,
                        content_type=3,  # 1：文本，2：html，3：markdown
                    )
                    msg = 'WxPusher通知{}'.format(res)
                    logger.info(msg)

                if notify.name == PushConfig.pushdeer_push:
                    pushdeer = PushDeer(
                        server=notify.custom_server,
                        pushkey=notify.corpsecret)
                    # res = pushdeer.send_text(text, desp="optional description")
                    res = pushdeer.send_markdown(text=text,
                                                 desp="#### 欢迎使用PTools，使用中遇到问题请在微信群进行反馈！")
                    msg = 'pushdeer通知{}'.format(res)
                    logger.info(msg)

                if notify.name == PushConfig.bark_push:
                    url = notify.custom_server + notify.corpsecret + '/' + text
                    res = self.get_scraper().get(url=url)
                    msg = 'bark通知{}'.format(res)
                    logger.info(msg)

                if notify.name == PushConfig.iyuu_push:
                    url = notify.custom_server + '{}.send'.format(notify.corpsecret)
                    # text = '# '
                    res = self.get_scraper().post(
                        url=url,
                        data={
                            'text': '欢迎使用PTools',
                            'desp': text
                        })
                    logger.info('爱语飞飞通知：{}'.format(res))
        except Exception as e:
            logger.info('通知发送失败，{} {}'.format(res, traceback.format_exc(limit=3)))

    def send_request(self,
                     my_site: MySite,
                     url: str,
                     method: str = 'get',
                     data: dict = None,
                     params: dict = None,
                     json: dict = None,
                     timeout: int = 45,
                     delay: int = 15,
                     proxies: dict = None):
        site = my_site.site
        scraper = self.get_scraper(delay=delay)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        _RESTRICTED_SERVER_CIPHERS = 'ALL'
        ssl_context.set_ciphers(_RESTRICTED_SERVER_CIPHERS)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = CERT_NONE
        scraper.ssl_context = ssl_context
        headers = {
            'User-Agent': my_site.user_agent,
        }
        for k, v in eval(site.sign_in_headers).items():
            headers[k] = v
        # logger.info(self.headers)
        # if site.url == 'https://hdchina.org/':
        #     pool = urllib3.HTTPSConnectionPool(host=site.url, port=443, check_hostname=False)
        #     res = pool.request(method=method, url=url, headers=headers, data=data, params=params)
        #     logger.info(res)
        #     return res
        # scraper.ssl_context = ssl_ctx
        return scraper.request(
            url=url,
            method=method,
            headers=headers,
            cookies=self.cookies2dict(my_site.cookie),
            data=data,
            timeout=timeout,
            proxies=proxies,
            params=params,
            json=json,
        )

    def ocr_captcha(self, img_url):
        """百度OCR高精度识别，传入图片URL"""
        # 获取百度识别结果
        ocr = OCR.objects.filter(enable=True).first()
        if not ocr:
            logger.error('未设置百度OCR文本识别API，无法使用本功能！')
            return CommonResponse.error(
                status=StatusCodeEnum.OCR_NO_CONFIG,
            )
        try:
            ocr_client = aip.AipOcr(appId=ocr.app_id, secretKey=ocr.secret_key, apiKey=ocr.api_key)
            res1 = ocr_client.basicGeneralUrl(img_url)
            logger.info(res1)
            if res1.get('error_code'):
                res1 = ocr_client.basicAccurateUrl(img_url)
            logger.info('res1: {}'.format(res1))
            if res1.get('error_code'):
                return CommonResponse.error(
                    status=StatusCodeEnum.OCR_ACCESS_ERR,
                    msg='{} {}'.format(StatusCodeEnum.OCR_ACCESS_ERR.errmsg, res1.get('error_msg'))
                )
            res2 = res1.get('words_result')[0].get('words')
            # 去除杂乱字符
            imagestring = ''.join(re.findall('[A-Za-z0-9]+', res2)).strip()
            logger_info = '百度OCR天空验证码：{}，长度：{}'.format(imagestring, len(imagestring))
            logger.info(logger_info)
            # 识别错误就重来

            return CommonResponse.success(
                status=StatusCodeEnum.OK,
                data=imagestring,
            )
        except Exception as e:
            msg = '百度OCR识别失败：{}'.format(e)
            logger.info(traceback.format_exc(limit=3))
            # raise
            self.send_text(msg)
            return CommonResponse.error(
                status=StatusCodeEnum.OCR_ACCESS_ERR,
                msg='{} {}'.format(StatusCodeEnum.OCR_ACCESS_ERR.errmsg, msg)
            )

    def parse_ptpp_cookies(self, data_list):
        # 解析前端传来的数据
        datas = json.loads(data_list.get('cookies'))
        info_list = json.loads(data_list.get('info'))
        userdata_list = json.loads(data_list.get('userdata'))
        cookies = []
        try:
            for data, info in zip(datas, info_list):
                cookie_list = data.get('cookies')
                host = data.get('host')
                cookie_str = ''
                for cookie in cookie_list:
                    cookie_str += '{}={};'.format(cookie.get('name'), cookie.get('value'))
                # logger.info(domain + cookie_str)
                cookies.append({
                    'url': data.get('url'),
                    'host': host,
                    'icon': info.get('icon'),
                    'info': info.get('user'),
                    'passkey': info.get('passkey'),
                    'cookies': cookie_str.rstrip(';'),
                    'userdatas': userdata_list.get(host)
                })
            logger.info('站点记录共{}条'.format(len(cookies)))
            # logger.info(cookies)
            return CommonResponse.success(data=cookies)
        except Exception as e:
            # raise
            # 打印异常详细信息
            logger.error(traceback.format_exc(limit=3))
            return CommonResponse.error(msg='Cookies解析失败，请确认导入了正确的cookies备份文件！{}'.format(e))

    # @transaction.atomic
    def get_uid_and_passkey(self, cookie: dict):
        url = cookie.get('url')
        host = cookie.get('host')
        site = Site.objects.filter(url__contains=host).first()
        # logger.info('查询站点信息：', site, site.url, url)
        if not site:
            return CommonResponse.error(msg='尚未支持此站点：{}'.format(url))
        icon = cookie.get('icon')
        if icon:
            site.logo = icon
        site.save()
        # my_site = MySite.objects.filter(site=site).first()
        # logger.info('查询我的站点：',my_site)
        # 如果有更新cookie，如果没有继续创建
        my_level_str = cookie.get('info').get('levelName')
        if my_level_str:
            my_level = re.sub(u'([^a-zA-Z_ ])', "", my_level_str)
        else:
            my_level = ' '
        userdatas = cookie.get('userdatas')
        time_stamp = cookie.get('info').get('joinTime')

        time_join = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time_stamp / 1000))

        passkey = cookie.get('passkey')
        logger.info('passkey: {}'.format(passkey))

        result = MySite.objects.update_or_create(site=site, defaults={
            'cookie': cookie.get('cookies'),
            'passkey': passkey,
            'user_id': cookie.get('info').get('id'),
            'my_level': my_level if my_level else ' ',
            'time_join': time_join,
            'seed': cookie.get('info').get('seeding') if cookie.get('info').get('seeding') else 0,
            'mail': cookie.get('info').get('messageCount') if cookie.get('info').get('messageCount') else 0,
        })
        my_site = result[0]
        passkey_msg = ''
        if not passkey:
            try:
                logger.info('PTPP未配置PASSKEY，尝试获取中')
                response = self.send_request(my_site, site.url + site.page_control_panel)
                passkey = self.parse(response, site.my_passkey_rule)[0]
                my_site.passkey = passkey
                my_site.save()
            except Exception as e:
                passkey_msg = '{} PassKey获取失败，请手动添加！'.format(site.name)
                logger.info(passkey_msg)
        logger.info('开始导入PTPP历史数据')
        for key, value in userdatas.items():
            logger.info(key)
            try:
                downloaded = value.get('downloaded')
                uploaded = value.get('uploaded')
                seeding_size = value.get('seedingSize')
                my_sp = value.get('bonus')
                ratio = value.get('ratio')
                if ratio is None or ratio == 'null':
                    continue
                if type(ratio) == str:
                    ratio = ratio.strip('\n').strip()
                if float(ratio) < 0:
                    ratio = 'inf'
                if not value.get(
                        'id') or key == 'latest' or not downloaded or not uploaded or not seeding_size or not my_sp:
                    continue
                create_time = dateutil.parser.parse(key).date()
                count_status = SiteStatus.objects.filter(site=my_site,
                                                         created_at__date=create_time).count()
                if count_status >= 1:
                    continue
                res_status = SiteStatus.objects.update_or_create(
                    site=my_site,
                    created_at__date=create_time,
                    defaults={
                        'uploaded': uploaded,
                        'downloaded': downloaded,
                        'my_sp': my_sp,
                        'seed_vol': seeding_size,
                        'ratio': float(ratio),
                    })
                logger.info('数据导入结果，True为新建，false为更新')
                logger.info(res_status)
            except Exception as e:
                msg = '{}{} 数据导入出错，错误原因：{}'.format(site.name, key, traceback.format_exc(limit=3))
                logger.error(msg)
                continue
        if not passkey:
            return CommonResponse.success(
                status=StatusCodeEnum.NO_PASSKEY_WARNING,
                msg=site.name + (' 信息导入成功！' if result[1] else ' 信息更新成功！ ') + passkey_msg
            )
        return CommonResponse.success(
            # status=StatusCodeEnum.NO_PASSKEY_WARNING,
            msg=site.name + (' 信息导入成功！' if result[1] else ' 信息更新成功！ ') + passkey_msg
        )

    @staticmethod
    def get_torrent_info_from_downloader(torrent_info: TorrentInfo):
        """
        通过种子信息，到下载器查询任务信息
        :param torrent_info:
        :return:
        """
        downloader = torrent_info.downloader
        if not downloader:
            return CommonResponse.error(
                msg='此种子未推送到下载器！'
            )
        if downloader.category == DownloaderCategory.Transmission:
            try:
                tr_client = transmission_rpc.Client(host=downloader.host,
                                                    port=downloader.port,
                                                    username=downloader.username,
                                                    password=downloader.password,
                                                    timeout=30)
                torrent = tr_client.get_torrents(ids=torrent_info.hash_string)
            except Exception as e:
                # 打印异常详细信息
                logger.error(traceback.format_exc(limit=3))
                return CommonResponse.error(
                    msg='下载无法连接，请检查下载器是否正常？！{}'.format(e)
                )
        elif downloader.category == DownloaderCategory.qBittorrent:
            try:
                qb_client = qbittorrentapi.Client(
                    host=downloader.host,
                    port=downloader.port,
                    username=downloader.username,
                    password=downloader.password,
                    # 仅返回简单JSON
                    # SIMPLE_RESPONSES=True
                )
                qb_client.auth_log_in()
                torrent = qb_client.torrents_info(hashes=torrent_info.hash_string)
            except Exception as e:
                # 打印异常详细信息
                logger.error(traceback.format_exc(limit=3))
                return CommonResponse.error(
                    msg='下载无法连接，请检查下载器是否正常？{}'.format(e)
                )
            # if downloader.category == DownloaderCategory.qBittorrent:
            #     pass
        else:
            return CommonResponse.error(
                msg='下载不存在，请检查下载器是否正常？'
            )
        return CommonResponse.success(
            data=torrent
        )

    @staticmethod
    def download_img(image_url):
        """
        下载图片并转为二进制流
        :param image_url:
        :return:
        """
        if image_url.startswith('http'):
            r = requests.get(image_url, timeout=5)
            img_data = r.content
        elif image_url.startswith('ftp'):
            with contextlib.closing(urlopen(image_url, None, 10)) as r:
                img_data = r.read()
        else:
            return False
        return img_data

    def sign_in_52pt(self, my_site: MySite):
        site = my_site.site
        url = site.url + site.page_sign_in.lstrip('/')
        result = self.send_request(
            my_site=my_site,
            url=url,
        )
        # sign_str = self.parse(result, '//font[contains(text(),"签过到")]/text()')
        sign_str = etree.HTML(result.text).xpath('//font[contains(text(),"签过到")]/text()')
        logger.info(sign_str)
        if len(sign_str) >= 1:
            # msg = self.parse(result, '//font[contains(text(),"签过到")]/text()')
            return CommonResponse.success(msg='您已成功签到，请勿重复操作！{}'.format(sign_str))
        # if len(sign_str) >= 1:
        #     return CommonResponse.success(msg='52PT 签到太复杂不支持，访问网站保持活跃成功！')
        questionid = self.parse(result, '//input[contains(@name, "questionid")]/@value')
        choices = self.parse(result, '//input[contains(@name, "choice[]")]/@value')
        # for choice in choices:
        #     logger.info(choice)
        data = {
            'questionid': questionid,
            'choice[]': choices[random.randint(0, len(choices) - 1)],
            'usercomment': '十步杀一人，千里不流行！',
            'wantskip': '不会'
        }
        logger.info(data)
        sign_res = self.send_request(
            my_site=my_site,
            url=site.url + site.page_sign_in.lstrip('/'),
            method=site.sign_in_method,
            data=data
        )
        logger.info(sign_res.text)
        sign_str = self.parse(sign_res, '//font[contains(text(),"签过到")]/text()')
        if len(sign_str) < 1:
            return CommonResponse.error(
                msg='签到失败!'
            )
        else:
            # msg = self.parse(sign_res, '//font[contains(text(),"签过到")]/text()')
            return CommonResponse.success(
                msg='签到成功！{}'.format(''.join(sign_str))
            )

    def sign_in_hdupt(self, my_site: MySite):
        site = my_site.site
        url = site.url + site.page_control_panel.lstrip('/')
        result = self.send_request(
            my_site=my_site,
            url=url,
        )
        sign_str = self.parse(result, '//span[@id="qiandao"]')
        logger.info(sign_str)
        if len(sign_str) < 1:
            return CommonResponse.success(msg=site.name + '已签到，请勿重复操作！！')
        sign_res = self.send_request(
            my_site=my_site,
            url=site.url + site.page_sign_in.lstrip('/'),
            method=site.sign_in_method
        ).text.encode('utf8')
        if sign_res.isdigit():
            return CommonResponse.success(
                msg='你还需要继续努力哦！此次签到，你获得了魔力奖励：{}'.format(sign_res)
            )
        return CommonResponse.error(
            msg=f'签到失败！{sign_res}'
        )

    def sign_in_hd4fans(self, my_site: MySite):
        site = my_site.site
        url = site.url + site.page_control_panel.lstrip('/')
        result = self.send_request(
            my_site=my_site,
            url=url,
        )
        sign_str = self.parse(result, '//span[@id="checkin"]/a')
        logger.info(sign_str)
        if len(sign_str) < 1:
            return CommonResponse.success(msg=site.name + '已签到，请勿重复操作！！')
        sign_res = self.send_request(
            my_site=my_site,
            url=site.url + site.page_sign_in.lstrip('/'),
            method=site.sign_in_method,
            params={
                'action': 'checkin'
            }
        )
        msg = '你还需要继续努力哦！此次签到，你获得了魔力奖励：{}'.format(sign_res.text.encode('utf8'))
        logger.info(msg)
        return CommonResponse.success(
            msg=msg
        )

    def sign_in_hdc(self, my_site: MySite):
        site = my_site.site
        url = site.url + site.page_control_panel.lstrip('/')
        result = self.send_request(
            my_site=my_site,
            url=url,
        )
        sign_str = self.parse(result, '//a[text()="已签到"]')
        logger.info('{}签到检测'.format(site.name, sign_str))
        if len(sign_str) >= 1:
            return CommonResponse.success(msg=site.name + '已签到，请勿重复操作！！')
        csrf = ''.join(self.parse(result, '//meta[@name="x-csrf"]/@content'))
        logger.info('CSRF字符串：{}'.format(csrf))
        sign_res = self.send_request(
            my_site=my_site,
            url=site.url + site.page_sign_in,
            method=site.sign_in_method,
            data={
                'csrf': csrf
            }
        )
        res_json = sign_res.json()
        logger.info('签到返回结果：{}'.format(res_json))
        if res_json.get('state') == 'success':
            if len(sign_res.cookies) >= 1:
                logger.info(f'我的COOKIE：{my_site.cookie}')
                logger.info(f'新的COOKIE字典：{sign_res.cookies.items()}')
                cookie = ''
                for k, v in sign_res.cookies.items():
                    cookie += f'{k}={v};'
                logger.info(f'新的COOKIE：{sign_res.cookies.items()}')
                my_site.cookie = cookie
                my_site.save()
            msg = f"签到成功，您已连续签到{res_json.get('signindays')}天，本次增加魔力:{res_json.get('integral')}。"
            logger.info(msg)
            return CommonResponse.success(
                msg=msg
            )
        else:
            msg = "签到失败"
            logger.info(msg)
            return CommonResponse.error(
                msg=msg
            )

    def sign_in_u2(self, my_site: MySite):
        site = my_site.site
        url = site.url + site.page_sign_in.lstrip('/')
        result = self.send_request(
            my_site=my_site,
            url=url,
        )
        sign_str = ''.join(self.parse(result, '//a[@href="showup.php"]/text()'))
        logger.info(site.name + sign_str)
        if '已签到' in converter.convert(sign_str):
            return CommonResponse.success(msg=site.name + '已签到，请勿重复操作！！')
        req = self.parse(result, '//form//td/input[@name="req"]/@value')
        hash_str = self.parse(result, '//form//td/input[@name="hash"]/@value')
        form = self.parse(result, '//form//td/input[@name="form"]/@value')
        submit_name = self.parse(result, '//form//td/input[@type="submit"]/@name')
        submit_value = self.parse(result, '//form//td/input[@type="submit"]/@value')
        message = site.sign_in_params if len(site.sign_in_params) >= 5 else '天空飘来五个字儿,幼儿园里没有事儿'
        logger.info(submit_name)
        logger.info(submit_value)
        param = []
        for name, value in zip(submit_name, submit_value):
            param.append({
                name: value
            })
        data = {
            'req': req[0],
            'hash': hash_str[0],
            'form': form[0],
            'message': message,
        }
        data.update(param[random.randint(0, 3)])
        logger.info(data)
        response = self.send_request(
            my_site,
            url=site.url + site.page_sign_in.lstrip('/') + '?action=show',
            method=site.sign_in_method,
            data=data,
        )
        logger.info(response.text.encode('utf8'))
        if "window.location.href = 'showup.php';" in response.text.encode('utf8'):
            result = self.send_request(
                my_site=my_site,
                url=url,
            )
            title = self.parse(result, '//h2[contains(text(),"签到区")]/following-sibling::table//h3/text()')
            content = self.parse(
                result,
                '//td/span[@class="nowrap"]/a[contains(@href,"userdetails.php?id={}")]/parent::span/following-sibling::b[2]/text()'.format(
                    my_site.user_id
                )
            )
            msg = '{}，奖励UCoin{}'.format(''.join(title), ''.join(content))
            logger.info(msg)
            return CommonResponse.success(msg=msg)
        else:
            logger.info('签到失败！')
            return CommonResponse.error(msg='签到失败！')

    def sign_in_opencd(self, my_site: MySite):
        """皇后签到"""
        site = my_site.site
        check_url = site.url + site.page_user
        res_check = self.send_request(
            my_site=my_site,
            method='get',
            url=check_url)
        href_sign_in = self.parse(res_check, '//a[@href="/plugin_sign-in.php?cmd=show-log"]')
        if len(href_sign_in) >= 1:
            return CommonResponse.success(
                status=StatusCodeEnum.OK,
                data={
                    'state': 'false'
                }
            )
        url = site.url + site.page_sign_in.lstrip('/')
        logger.info('# 开启验证码！')
        res = self.send_request(
            my_site=my_site,
            method='get',
            url=url)
        logger.info(res.text.encode('utf-8'))
        img_src = ''.join(self.parse(res, '//form[@id="frmSignin"]//img/@src'))
        img_get_url = site.url + img_src
        times = 0
        # imagestring = ''
        ocr_result = None
        while times <= 5:
            ocr_result = self.ocr_captcha(img_get_url)
            if ocr_result.code == StatusCodeEnum.OK.code:
                imagestring = ocr_result.data
                logger.info('验证码长度：{}'.format(len(imagestring)))
                if len(imagestring) == 6:
                    break
            times += 1
            time.sleep(1)
        if ocr_result.code != StatusCodeEnum.OK.code:
            return ocr_result
        data = {
            'imagehash': ''.join(self.parse(res, '//form[@id="frmSignin"]//input[@name="imagehash"]/@value')),
            'imagestring': imagestring
        }
        logger.info('请求参数：{}'.format(data))
        result = self.send_request(
            my_site=my_site,
            method=site.sign_in_method,
            url=site.url + 'plugin_sign-in.php?cmd=signin', data=data)
        logger.info('皇后签到返回值：{}  \n'.format(result.text.encode('utf-8')))
        return CommonResponse.success(
            status=StatusCodeEnum.OK,
            data=result.json()
        )

    def sign_in_hdsky(self, my_site: MySite, captcha=False):
        """HDSKY签到"""
        site = my_site.site
        url = site.url + site.page_sign_in.lstrip('/')
        # sky无需验证码时使用本方案
        if not captcha:
            result = self.send_request(
                my_site=my_site,
                method=site.sign_in_method,
                url=url,
                data=eval(site.sign_in_params))
        # sky无验证码方案结束
        else:
            # 获取img hash
            logger.info('# 开启验证码！')
            res = self.send_request(
                my_site=my_site,
                method='post',
                url=site.url + 'image_code_ajax.php',
                data={
                    'action': 'new'
                }).json()
            # img url
            img_get_url = site.url + 'image.php?action=regimage&imagehash=' + res.get('code')
            logger.info('验证码图片链接：' + img_get_url)
            # 获取OCR识别结果
            # imagestring = self.ocr_captcha(img_url=img_get_url)
            times = 0
            # imagestring = ''
            ocr_result = None
            while times <= 5:
                # ocr_result = self.ocr_captcha(img_get_url)
                ocr_result = self.ocr_captcha(img_get_url)
                if ocr_result.code == StatusCodeEnum.OK.code:
                    imagestring = ocr_result.data
                    logger.info('验证码长度：{}'.format(len(imagestring)))
                    if len(imagestring) == 6:
                        break
                times += 1
                time.sleep(1)
            if ocr_result.code != StatusCodeEnum.OK.code:
                return ocr_result
            # 组装请求参数
            data = {
                'action': 'showup',
                'imagehash': res.get('code'),
                'imagestring': imagestring
            }
            # logger.info('请求参数', data)
            result = self.send_request(
                my_site=my_site,
                method=site.sign_in_method,
                url=url, data=data)
        logger.info('天空返回值：{}\n'.format(result.text))
        return CommonResponse.success(
            status=StatusCodeEnum.OK,
            data=result.json()
        )

    def sign_in_ttg(self, my_site: MySite):
        """
        TTG签到
        :param my_site:
        :return:
        """
        site = my_site.site
        url = site.url + site.page_user.format(my_site.user_id)
        logger.info(site.name + '个人主页：' + url)
        try:
            res = self.send_request(my_site=my_site, url=url)
            # logger.info(res.text.encode('utf8'))
            # html = self.parse(res, '//script/text()')
            html = etree.HTML(res.text).xpath('//script/text()')
            # logger.info(html)
            text = ''.join(html).replace('\n', '').replace(' ', '')
            logger.info(text)
            signed_timestamp = get_decimals(re.search("signed_timestamp:\"\d{10}", text).group())

            signed_token = re.search('[a-zA-Z0-9]{32}', text).group()
            params = {
                'signed_timestamp': signed_timestamp,
                'signed_token': signed_token
            }
            logger.info('signed_timestamp:' + signed_timestamp)
            logger.info('signed_token:' + signed_token)

            resp = self.send_request(
                my_site,
                site.url + site.page_sign_in,
                method=site.sign_in_method,
                data=params)
            logger.info(resp.text)
            return CommonResponse.success(
                status=StatusCodeEnum.OK,
                msg=resp.content.decode('utf8')
            )
        except Exception as e:
            # 打印异常详细信息
            logger.error(traceback.format_exc(limit=3))
            return CommonResponse.success(
                status=StatusCodeEnum.WEB_CONNECT_ERR,
                msg='{} 签到失败: {}'.format(site.name, e)
            )

    @staticmethod
    def get_user_torrent(html, rule):
        res_list = html.xpath(rule)
        logger.info('content' + res_list)
        # logger.info('res_list:', len(res_list))
        return '0' if len(res_list) == 0 else res_list[0]

    def do_sign_in(self, pool, queryset: QuerySet[MySite]):
        message_list = '# 自动签到通知  \n\n### <font color="orange">未显示的站点已经签到过了哟！</font>  \n\n'
        if datetime.now().hour < 9:
            # U2/52PT 每天九点前不签到
            queryset = [my_site for my_site in queryset if my_site.site.url not in [
                'https://u2.dmhy.org/', 'https://52pt.site/'
            ] and my_site.signin_set.filter(created_at__date__gte=datetime.today()).count() <= 0
                        and my_site.cookie]
            message = '> <font color="red">站点：`U2`以及`52PT` 早上九点之前不执行签到任务哦！</font>  \n\n'
            logger.info(message)
            message_list = message + message_list
        else:
            queryset = [my_site for my_site in queryset if my_site.cookie and
                        my_site.signin_set.filter(created_at__date__gte=datetime.today(),
                                                  sign_in_today=True).count() <= 0]
        logger.info(len(queryset))
        if len(queryset) <= 0:
            message_list = '> <font color="orange">已全部签到或无需签到！</font>  \n\n'
            logger.info(message_list)
            return 0
        # results = pool.map(pt_spider.sign_in, site_list)
        with lock:
            results = pool.map(self.sign_in, queryset)
            for my_site, result in zip(queryset, results):
                logger.info('自动签到：{}, {}'.format(my_site, result))
                if result.code == StatusCodeEnum.OK.code:
                    message_list += (
                            '> <font color="orange">' + my_site.site.name + '</font> 签到成功！' + converter.convert(
                        result.msg) + '  \n\n')
                    logger.info(my_site.site.name + '签到成功！' + result.msg)
                else:
                    message = '> <font color="red">' + my_site.site.name + ' 签到失败！' + result.msg + '</font>  \n\n'
                    message_list = message + message_list
                    logger.error(my_site.site.name + '签到失败！原因：' + result.msg)
            return message_list

    # @transaction.atomic
    def sign_in(self, my_site: MySite):
        """签到"""
        site = my_site.site
        logger.info(site.name + '开始签到')
        signin_today = my_site.signin_set.filter(created_at__date__gte=datetime.today()).first()
        # 如果已有签到记录
        if signin_today:
            if signin_today.sign_in_today is True:
                return CommonResponse.success(msg='已签到，请勿重复签到！')
        else:
            signin_today = SignIn(site=my_site)
        url = site.url + site.page_sign_in.lstrip('/')
        logger.info('签到链接：' + url)
        try:
            # with lock:
            if '52pt' in site.url or 'chdbits' in site.url:
                result = self.sign_in_52pt(my_site)
                if result.code == StatusCodeEnum.OK.code:
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = result.msg
                    signin_today.save()
                return result
            if 'hd4fans' in site.url:
                result = self.sign_in_hd4fans(my_site)
                if result.code == StatusCodeEnum.OK.code:
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = result.msg
                    signin_today.save()
                return result
            if 'hdupt.com' in site.url:
                result = self.sign_in_hdupt(my_site)
                if result.code == StatusCodeEnum.OK.code:
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = result.msg
                    signin_today.save()
                return result
            if 'hdchina' in site.url:
                result = self.sign_in_hdc(my_site)
                if result.code == StatusCodeEnum.OK.code:
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = result.msg
                    signin_today.save()
                return result
            if 'totheglory' in site.url:
                result = self.sign_in_ttg(my_site)
                if result.code == StatusCodeEnum.OK.code:
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = result.msg
                    signin_today.save()
                return result
            if 'u2.dmhy.org' in site.url:
                result = self.sign_in_u2(my_site)
                if result.code == StatusCodeEnum.OK.code:
                    logger.info(result.data)
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = result.msg
                    signin_today.save()
                return result
            if 'hdsky.me' in site.url:
                result = self.sign_in_hdsky(my_site=my_site, captcha=site.sign_in_captcha)
                if result.code == StatusCodeEnum.OK.code:
                    res_json = result.data
                    if res_json.get('success'):
                        # 签到成功
                        bonus = res_json.get('message')
                        days = (int(bonus) - 10) / 2 + 1
                        signin_today.sign_in_today = True
                        message = '成功,已连续签到{}天,魔力值加{},明日继续签到可获取{}魔力值！'.format(
                            days,
                            bonus,
                            bonus + 2
                        )
                        signin_today.sign_in_info = message
                        signin_today.save()
                        return CommonResponse.success(
                            status=StatusCodeEnum.OK,
                            msg=message
                        )
                    elif res_json.get('message') == 'date_unmatch':
                        # 重复签到
                        message = '您今天已经在其他地方签到了哦！'
                        signin_today.sign_in_today = True
                        signin_today.sign_in_info = message
                        signin_today.save()
                        return CommonResponse.success(
                            msg=message
                        )
                    elif res_json.get('message') == 'invalid_imagehash':
                        # 验证码错误
                        return CommonResponse.error(
                            status=StatusCodeEnum.IMAGE_CODE_ERR,
                        )
                    else:
                        # 签到失败
                        return CommonResponse.error(
                            status=StatusCodeEnum.FAILED_SIGN_IN,
                        )
                else:
                    # 签到失败
                    return result
            if 'open.cd' in site.url:
                result = self.sign_in_opencd(my_site=my_site)
                logger.info('皇后签到结果：{}'.format(result.to_dict()))
                if result.code == StatusCodeEnum.OK.code:
                    res_json = result.data
                    if res_json.get('state') == 'success':
                        signin_today.sign_in_today = True
                        # data = res_json.get('msg')
                        message = "签到成功，您已连续签到{}天，本次增加魔力:{}。".format(
                            res_json.get('signindays'),
                            res_json.get('integral'),
                        )
                        signin_today.sign_in_info = message
                        signin_today.save()
                        return CommonResponse.success(
                            status=StatusCodeEnum.OK,
                            msg=message
                        )
                    elif res_json.get('state') == 'false' and len(res_json) <= 1:
                        # 重复签到
                        message = '您今天已经在其他地方签到了哦！'
                        signin_today.sign_in_today = True
                        signin_today.sign_in_info = message
                        signin_today.save()
                        return CommonResponse.success(
                            msg=message
                        )
                    # elif res_json.get('state') == 'invalid_imagehash':
                    #     # 验证码错误
                    #     return CommonResponse.error(
                    #         status=StatusCodeEnum.IMAGE_CODE_ERR,
                    #     )
                    else:
                        # 签到失败
                        return CommonResponse.error(
                            status=StatusCodeEnum.FAILED_SIGN_IN,
                            msg=res_json.get('msg')
                        )
                else:
                    # 签到失败
                    return result
            if 'hdarea.co' in site.url:
                res = self.send_request(my_site=my_site,
                                        method=site.sign_in_method,
                                        url=url,
                                        data=eval(site.sign_in_params), )
                if res.status_code == 200:
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = res.text.encode('utf8')
                    signin_today.save()
                    return CommonResponse.success(msg=res.text)
                elif res.status_code == 503:
                    return CommonResponse.error(
                        status=StatusCodeEnum.COOKIE_EXPIRE,
                    )
                else:
                    return CommonResponse.error(
                        status=StatusCodeEnum.WEB_CONNECT_ERR,
                        msg=StatusCodeEnum.WEB_CONNECT_ERR.errmsg + '签到失败！'
                    )
            if 'wintersakura' in site.url:
                # 单独发送请求，解决冬樱签到问题
                res = requests.get(url=url, verify=False, cookies=cookie2dict(my_site.cookie), headers={
                    'user-agent': my_site.user_agent
                })
                logger.info(res.text)
            else:
                res = self.send_request(my_site=my_site, method=site.sign_in_method, url=url,
                                        data=eval(site.sign_in_params))
            logger.info(res.status_code)
            if 'pterclub.com' in site.url:
                logger.info(f'猫站签到返回值：{res.json()}')
                status = res.json().get('status')
                logger.info('{}：{}'.format(site.name, status))
                '''
                {
                  "status": "0",
                  "data": "抱歉",
                  "message": "您今天已经签到过了，请勿重复刷新。"
                }
                {
                  "status": "1",
                  "data": "&nbsp;(签到已得12)",
                  "message": "<p>这是您的第 <b>2</b> 次签到，已连续签到 <b>1</b> 天。</p><p>本次签到获得 <b>12</b> 克猫粮。</p>"
                }
                '''
                if status == '0' or status == '1':
                    message = res.json().get('message')
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = message
                    signin_today.save()
                    return CommonResponse.success(
                        msg=message
                    )
                else:
                    return CommonResponse.success(
                        msg='签到失败！'
                    )
            if 'hares.top' in site.url:
                logger.info(res.text)
                code = res.json().get('code')
                # logger.info('白兔返回码：'+ type(code))
                if int(code) == 0:
                    """
                    "datas": {
                      "id": 2273,
                      "uid": 2577,
                      "added": "2022-08-03 12:52:36",
                      "points": "200",
                      "total_points": 5435,
                      "days": 42,
                      "total_days": 123,
                      "added_time": "12:52:36",
                      "is_updated": 1
                    }
                    """
                    message_template = '签到成功！奖励奶糖{},奶糖总奖励是{},您已连续签到{}天，签到总天数{}天！'
                    data = res.json().get('datas')
                    message = message_template.format(data.get('points'),
                                                      data.get('total_points'),
                                                      data.get('days'),
                                                      data.get('total_days'))
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = message
                    signin_today.save()
                    return CommonResponse.success(msg=message)
                elif int(code) == 1:
                    message = res.json().get('msg')
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = message
                    signin_today.save()
                    return CommonResponse.success(
                        msg=message
                    )
                else:
                    return CommonResponse.error(
                        status=StatusCodeEnum.FAILED_SIGN_IN
                    )
            if 'btschool' in site.url:
                # logger.info(res.status_code)
                logger.info('学校签到：{}'.format(res.text.encode('utf-8')))
                text = self.parse(res, '//script/text()')
                logger.info('解析签到返回信息：{}'.format(text))
                if len(text) > 0:
                    location = self.parse_school_location(text)
                    logger.info('学校签到链接：' + location)
                    if 'addbouns.php' in location:
                        res = self.send_request(my_site=my_site, url=site.url + location.lstrip('/'))
                sign_in_text = self.parse(res, '//a[@href="index.php"]/font//text()')
                sign_in_stat = self.parse(res, '//a[contains(@href,"addbouns")]')
                logger.info('{} 签到反馈：{}'.format(site.name, sign_in_text))
                if res.status_code == 200 and len(sign_in_stat) <= 0:
                    message = ''.join(sign_in_text) if len(sign_in_text) >= 1 else '您已在其他地方签到，请勿重复操作！'
                    signin_today.sign_in_today = True
                    signin_today.sign_in_info = message
                    signin_today.save()
                    return CommonResponse.success(msg=message)
                return CommonResponse.error(msg='签到失败！请求响应码：{}'.format(res.status_code))
            if res.status_code == 200:
                status = converter.convert(res.text.encode('utf8'))
                logger.info(status)
                # status = ''.join(self.parse(res, '//a[contains(@href,{})]/text()'.format(site.page_sign_in)))
                # 检查是否签到成功！
                # if '签到得魔力' in converter.convert(status):
                haidan_sign_str = '<input type="submit" id="modalBtn" ' \
                                  'style="cursor: default;" disabled class="dt_button" value="已经打卡" />'
                if haidan_sign_str in status \
                        or '(获得' in status \
                        or '签到已得' in status \
                        or '已签到' in status \
                        or '已经签到' in status \
                        or '签到成功' in status:
                    pass
                else:
                    return CommonResponse.error(msg='签到失败！')
                title_parse = self.parse(res, '//td[@id="outer"]//td[@class="embedded"]/h2/text()')
                content_parse = self.parse(res, '//td[@id="outer"]//td[@class="embedded"]/table/tr/td//text()')
                if len(content_parse) <= 0:
                    title_parse = self.parse(res, '//td[@id="outer"]//td[@class="embedded"]/b[1]/text()')
                    content_parse = self.parse(res, '//td[@id="outer"]//td[@class="embedded"]/text()[1]')
                if 'hdcity' in site.url:
                    title_parse = self.parse(
                        res,
                        '//p[contains(text(),"本次签到获得魅力")]/preceding-sibling::h1[1]/span/text()'
                    )
                    content_parse = self.parse(res, '//p[contains(text(),"本次签到获得魅力")]/text()')
                title = ''.join(title_parse).strip()
                # logger.info(content_parse)
                content = ''.join(content_parse).strip().replace('\n', '')
                # logger.info(content)
                message = title + '，' + content
                if len(message) <= 1:
                    message = datetime.today().strftime('%Y-%m-%d %H:%M:%S') + '打卡成功！'
                # message = ''.join(title).strip()
                signin_today.sign_in_today = True
                signin_today.sign_in_info = message
                signin_today.save()
                logger.info(site.name + message)
                return CommonResponse.success(msg=message)
            else:
                return CommonResponse.error(msg='请确认签到是否成功？？网页返回码：' + str(res.status_code))
        except Exception as e:
            msg = '{}签到失败！原因：{}'.format(site.name, e)
            logger.error(msg)
            logger.error(traceback.format_exc(limit=3))
            # raise
            # self.send_text(msg)
            return CommonResponse.error(msg=msg)

    @staticmethod
    def parse(response, rules):
        return etree.HTML(response.text.replace('0xff', '')).xpath(rules)

    def send_torrent_info_request(self, my_site: MySite):
        site = my_site.site
        url = site.url + site.page_default.lstrip('/')
        logger.info(f'种子页面链接：{url}')
        try:
            response = self.send_request(my_site, url)
            logger.info(site.name)
            if response.status_code == 200:
                return CommonResponse.success(data=response)
            elif response.status_code == 503:
                return CommonResponse.error(status=StatusCodeEnum.WEB_CLOUD_FLARE)
            else:
                return CommonResponse.error(msg="网站访问失败")
        except Exception as e:
            # raise
            msg = '{} 网站访问失败！原因：{}'.format(site.name, e)
            # 打印异常详细信息
            logger.error(msg)
            logger.error(traceback.format_exc(limit=3))
            self.send_text(msg)
            return CommonResponse.error(msg=msg)

    # @transaction.atomic
    def get_torrent_info_list(self, my_site: MySite, response: Response):
        count = 0
        new_count = 0
        site = my_site.site
        if not my_site.passkey:
            return CommonResponse.error(msg='{}站点未设置Passkey，无法拼接种子链接！'.format(site.name))
        # logger.info(response.text.encode('utf8'))
        try:
            with lock:
                if site.url == 'https://www.hd.ai/':
                    # logger.info(response.text)
                    torrent_info_list = response.json().get('data').get('items')
                    logger.info('海带首页种子数目：{}'.format(len(torrent_info_list)))
                    for torrent_json_info in torrent_info_list:
                        # logger.info(torrent_json_info.get('download'))
                        magnet_url = site.url + torrent_json_info.get('download')
                        sale_num = torrent_json_info.get('promotion_time_type')
                        # logger.info(type(sale_status))
                        if sale_num == 1:
                            continue
                        # logger.info(type(sale_num))
                        name = torrent_json_info.get('name')
                        title = torrent_json_info.get('small_descr')
                        download_url = site.url + torrent_json_info.get('download').lstrip('/')
                        result = TorrentInfo.objects.update_or_create(download_url=download_url, defaults={
                            'category': torrent_json_info.get('category'),
                            'site': site,
                            'name': name,
                            'title': title if title != '' else name,
                            'magnet_url': magnet_url,
                            'poster_url': torrent_json_info.get('poster'),
                            'detail_url': torrent_json_info.get('details'),
                            'sale_status': TorrentBaseInfo.sale_list.get(sale_num),
                            'sale_expire': torrent_json_info.get('promotion_until'),
                            'hr': True,
                            'on_release': torrent_json_info.get('added'),
                            'size': int(torrent_json_info.get('size')),
                            'seeders': torrent_json_info.get('seeders'),
                            'leechers': torrent_json_info.get('leechers'),
                            'completers': torrent_json_info.get('times_completed'),
                            'save_path': '/downloads/brush'
                        })
                        # logger.info(result[0].site.url)
                        if not result[1]:
                            count += 1
                        else:
                            new_count += 1
                            # logger.info(torrent_info)
                else:
                    # response = self.send_request()
                    trs = self.parse(response, site.torrents_rule)
                    # logger.info(f'种子页面：{response.text}')
                    # logger.info(trs)
                    logger.info(len(trs))
                    print('=' * 50)
                    for tr in trs:
                        logger.info(tr)
                        # logger.info(etree.tostring(tr))
                        sale_status = ''.join(tr.xpath(site.sale_rule))
                        logger.info('sale_status: {}'.format(sale_status))
                        # 非免费种子跳过
                        if not sale_status:
                            logger.info('非免费种子跳过')
                            continue
                        title_list = tr.xpath(site.title_rule)
                        logger.info(title_list)
                        title = ''.join(title_list).strip().strip('剩余时间：').strip('剩餘時間：').strip('()')
                        name = ''.join(tr.xpath(site.name_rule))
                        if not name and not title:
                            logger.info('无名无姓？跳过')
                            continue
                        # sale_status = ''.join(re.split(r'[^\x00-\xff]', sale_status))
                        sale_status = sale_status.replace('tStatus ', '').upper().replace(
                            'FREE', 'Free'
                        ).replace('免费', 'Free').replace(' ', '')
                        # # 下载链接，下载链接已存在则跳过
                        href = ''.join(tr.xpath(site.magnet_url_rule))
                        logger.info('href: {}'.format(href))
                        magnet_url = '{}{}'.format(
                            site.url,
                            href.replace('&type=zip', '').replace(site.url, '').lstrip('/')
                        )
                        logger.info('magnet_url: {}'.format(magnet_url))
                        if href.count('passkey') <= 0 and href.count('&sign=') <= 0:
                            download_url = '{}&passkey={}'.format(magnet_url, my_site.passkey)
                        else:
                            download_url = magnet_url
                        logger.info('download_url: {}'.format(download_url))

                        # 如果种子有HR，则为否 HR绿色表示无需，红色表示未通过HR考核
                        hr = False if tr.xpath(site.hr_rule) else True
                        # H&R 种子有HR且站点设置不下载HR种子,跳过，
                        if not hr and not my_site.hr:
                            logger.info('hr种子，未开启HR跳过')
                            continue
                        # # 促销到期时间
                        sale_expire = ''.join(tr.xpath(site.sale_expire_rule))
                        if site.url in [
                            'https://www.beitai.pt/',
                            'http://www.oshen.win/',
                            'https://www.hitpt.com/',
                            'https://hdsky.me/',
                            'https://pt.keepfrds.com/',
                            # 'https://totheglory.im/',
                        ]:
                            """
                            由于备胎等站优惠结束日期格式特殊，所以做特殊处理,使用正则表达式获取字符串中的时间
                            """
                            sale_expire = ''.join(
                                re.findall(r'\d{4}\D\d{2}\D\d{2}\D\d{2}\D\d{2}\D', ''.join(sale_expire)))

                        if site.url in [
                            'https://totheglory.im/',
                        ]:
                            # javascript: alert('Freeleech将持续到2022年09月20日13点46分,加油呀~')
                            # 获取时间数据
                            time_array = re.findall(r'\d+', ''.join(sale_expire))
                            # 不组9位
                            time_array.extend([0, 0, 0, 0])
                            # 转化为标准时间字符串
                            sale_expire = time.strftime(
                                "%Y-%m-%d %H:%M:%S",
                                time.struct_time(tuple([int(x) for x in time_array]))
                            )
                        #     pass
                        # logger.info(sale_expire)
                        # 如果促销结束时间为空，则为无限期
                        sale_expire = '无限期' if not sale_expire else sale_expire
                        # logger.info(torrent_info.sale_expire)
                        # # 发布时间
                        on_release = ''.join(tr.xpath(site.release_rule))
                        # # 做种人数
                        seeders = ''.join(tr.xpath(site.seeders_rule))
                        # # # 下载人数
                        leechers = ''.join(tr.xpath(site.leechers_rule))
                        # # # 完成人数
                        completers = ''.join(tr.xpath(site.completers_rule))
                        # 存在则更新，不存在就创建
                        # logger.info(type(seeders), type(leechers), type(completers), )
                        # logger.info(seeders, leechers, completers)
                        # logger.info(''.join(tr.xpath(site.name_rule)))
                        category = ''.join(tr.xpath(site.category_rule))
                        file_parse_size = ''.join(tr.xpath(site.size_rule))
                        # file_parse_size = ''.join(tr.xpath(''))
                        logger.info(file_parse_size)
                        file_size = FileSizeConvert.parse_2_byte(file_parse_size)
                        # title = title if title else name
                        poster_url = ''.join(tr.xpath(site.poster_rule))  # 海报链接
                        detail_url = site.url + ''.join(
                            tr.xpath(site.detail_url_rule)
                        ).replace(site.url, '').lstrip('/')
                        logger.info('name：{}'.format(site))
                        logger.info('size{}'.format(file_size))
                        logger.info('category：{}'.format(category))
                        logger.info('download_url：{}'.format(download_url))
                        logger.info('magnet_url：{}'.format(magnet_url))
                        logger.info('title：{}'.format(title))
                        logger.info('poster_url：{}'.format(poster_url))
                        logger.info('detail_url：{}'.format(detail_url))
                        logger.info('sale_status：{}'.format(sale_status))
                        logger.info('sale_expire：{}'.format(sale_expire))
                        logger.info('seeders：{}'.format(seeders))
                        logger.info('leechers：{}'.format(leechers))
                        logger.info('H&R：{}'.format(hr))
                        logger.info('completers：{}'.format(completers))
                        result = TorrentInfo.objects.update_or_create(site=site, detail_url=detail_url, defaults={
                            'category': category,
                            'download_url': download_url,
                            'magnet_url': magnet_url,
                            'name': name,
                            'title': title,
                            'poster_url': poster_url,  # 海报链接
                            'detail_url': detail_url,
                            'sale_status': sale_status,
                            'sale_expire': sale_expire,
                            'hr': hr,
                            'on_release': on_release,
                            'size': file_size,
                            'seeders': seeders if seeders else '0',
                            'leechers': leechers if leechers else '0',
                            'completers': completers if completers else '0',
                            'save_path': '/downloads/brush'
                        })
                        logger.info('拉取种子：{} {}'.format(site.name, result[0]))
                        # time.sleep(0.5)
                        if not result[1]:
                            count += 1
                        else:
                            new_count += 1
                            # logger.info(torrent_info)
                if count + new_count <= 0:
                    return CommonResponse.error(msg='抓取失败或无促销种子！')
                return CommonResponse.success(data=(new_count, count))
        except Exception as e:
            # raise
            # self.send_text(site.name + '解析种子信息：失败！原因：' + str(e))
            msg = '解析种子页面失败！{}'.format(e)
            logger.error(msg)
            logger.error(traceback.format_exc(limit=3))
            return CommonResponse.error(msg=msg)

    # 从种子详情页面爬取种子HASH值
    def get_hash(self, torrent_info: TorrentInfo):
        site = torrent_info.site
        url = site.url + torrent_info.detail_url

        response = self.send_request(site.mysite, url)
        # logger.info(site, url, response.text)
        # html = self.parse(response, site.hash_rule)
        # has_string = self.parse(response, site.hash_rule)
        # magnet_url = self.parse(response, site.magnet_url_rule)
        hash_string = self.parse(response, '//tr[10]//td[@class="no_border_wide"][2]/text()')
        magnet_url = self.parse(response, '//a[contains(@href,"downhash")]/@href')
        torrent_info.hash_string = hash_string[0].replace('\xa0', '')
        torrent_info.magnet_url = magnet_url[0]
        logger.info('种子HASH及下载链接：{}'.format(hash_string, magnet_url))
        torrent_info.save()
        # logger.info(''.join(html))
        # torrent_hash = html[0].strip('\xa0')
        # TorrentInfo.objects.get(id=torrent_info.id).update(torrent_hash=torrent_hash)

    # 生产者消费者模式测试
    def send_status_request(self, my_site: MySite):
        site = my_site.site
        user_detail_url = site.url + site.page_user.lstrip('/').format(my_site.user_id)
        logger.info(user_detail_url)
        # uploaded_detail_url = site.url + site.page_uploaded.lstrip('/').format(my_site.user_id)
        seeding_detail_url = site.url + site.page_seeding.lstrip('/').format(my_site.user_id)
        # completed_detail_url = site.url + site.page_completed.lstrip('/').format(my_site.user_id)
        # leeching_detail_url = site.url + site.page_leeching.lstrip('/').format(my_site.user_id)
        try:
            # 发送请求，做种信息与正在下载信息，个人主页
            if 'wintersakura' in site.url:
                # 单独发送请求，解决冬樱签到问题
                user_detail_res = requests.get(url=user_detail_url, verify=False, cookies=cookie2dict(my_site.cookie),
                                               headers={
                                                   'user-agent': my_site.user_agent
                                               })
            else:
                user_detail_res = self.send_request(my_site=my_site, url=user_detail_url)
            # if leeching_detail_res.status_code != 200:
            #     return site.name + '种子下载信息获取错误，错误码：' + str(leeching_detail_res.status_code), False
            if user_detail_res.status_code != 200:
                return CommonResponse.error(
                    status=StatusCodeEnum.WEB_CONNECT_ERR,
                    msg=site.name + '个人主页访问错误，错误码：' + str(user_detail_res.status_code)
                )
            # logger.info(user_detail_res.status_code)
            logger.info('个人主页：{}'.format(user_detail_res.content))
            # 解析HTML
            # logger.info(user_detail_res.is_redirect)

            if 'totheglory' in site.url:
                # ttg的信息都是直接加载的，不需要再访问其他网页，直接解析就好
                details_html = etree.HTML(user_detail_res.content)
                seeding_html = details_html.xpath('//div[@id="ka2"]/table')[0]
            elif 'greatposterwall' in site.url or 'dicmusic' in site.url:
                details_html = user_detail_res.json()
                seeding_html = self.send_request(my_site=my_site, url=site.url + site.page_mybonus).json()
            elif 'lemonhd.org' in site.url:
                logger.info(site.url)
                details_html = etree.HTML(converter.convert(user_detail_res.text))
                seeding_html = details_html
            elif 'hdchina.org' in site.url:
                details_html = etree.HTML(converter.convert(user_detail_res.text))
                csrf = details_html.xpath('//meta[@name="x-csrf"]/@content')
                seeding_detail_res = self.send_request(my_site=my_site, url=seeding_detail_url, method='post',
                                                       data={
                                                           'userid': my_site.user_id,
                                                           'type': 'seeding',
                                                           'csrf': ''.join(csrf)
                                                       })
                seeding_html = etree.HTML(converter.convert(seeding_detail_res.text))
            else:
                details_html = etree.HTML(converter.convert(user_detail_res.text))

                if 'btschool' in site.url:
                    text = details_html.xpath('//script/text()')
                    logger.info('学校：{}'.format(text))
                    if len(text) > 0:
                        try:
                            location = self.parse_school_location(text)
                            logger.info('学校重定向链接：{}'.format(location))
                            if '__SAKURA' in location:
                                res = self.send_request(my_site=my_site, url=site.url + location.lstrip('/'), delay=25)
                                details_html = etree.HTML(res.text)
                                # logger.info(res.content)
                        except Exception as e:
                            logger.info('BT学校获取做种信息有误！')
                            pass
                if 'wintersakura' in site.url:
                    # 单独发送请求，解决冬樱签到问题
                    seeding_detail_res = requests.get(url=seeding_detail_url, verify=False,
                                                      cookies=cookie2dict(my_site.cookie),
                                                      headers={
                                                          'user-agent': my_site.user_agent
                                                      })
                else:
                    seeding_detail_res = self.send_request(my_site=my_site, url=seeding_detail_url, delay=25)
                logger.info('做种信息：{}'.format(seeding_detail_res.text))
                # leeching_detail_res = self.send_request(my_site=my_site, url=leeching_detail_url, timeout=25)
                if seeding_detail_res.status_code != 200:
                    return CommonResponse.error(
                        status=StatusCodeEnum.WEB_CONNECT_ERR,
                        msg='{} 做种信息访问错误，错误码：{}'.format(site.name, str(seeding_detail_res.status_code))
                    )
                seeding_html = etree.HTML(converter.convert(seeding_detail_res.text))
            # leeching_html = etree.HTML(leeching_detail_res.text)
            # logger.info(seeding_detail_res.text.encode('utf8'))
            return CommonResponse.success(data={
                'details_html': details_html,
                'seeding_html': seeding_html,
                # 'leeching_html': leeching_html
            })
        except NewConnectionError as nce:
            return CommonResponse.error(
                status=StatusCodeEnum.WEB_CONNECT_ERR,
                msg='打开网站失败，请检查网站是否维护？？')
        except ReadTimeout as e:
            return CommonResponse.error(
                status=StatusCodeEnum.WEB_CONNECT_ERR,
                msg='网站访问超时，请检查网站是否维护？？')
        except Exception as e:
            message = '{} 访问个人主页信息：失败！原因：{}'.format(my_site.site.name, e)
            logger.error(message)
            logger.error(traceback.format_exc(limit=3))
            # self.send_text(message)
            # raise
            return CommonResponse.error(msg=message)

    @staticmethod
    def parse_school_location(text: list):
        logger.info('解析学校访问链接：{}'.format(text))
        list1 = [x.strip().strip('"') for x in text[0].split('+')]
        list2 = ''.join(list1).split('=', 1)[1]
        return list2.strip(';').strip('"')

    @staticmethod
    def parse_message_num(messages: str):
        """
        解析网站消息条数
        :param messages:
        :return:
        """
        list1 = messages.split('(')
        if len(list1) > 1:
            count = re.sub(u"([^(\u0030-\u0039])", "", list1[1])
        elif len(list1) == 1:
            count = messages
        else:
            count = 0
        return int(count)

    # @transaction.atomic
    def parse_status_html(self, my_site: MySite, result: dict):
        """解析个人状态"""
        with lock:
            site = my_site.site
            details_html = result.get('details_html')
            seeding_html = result.get('seeding_html')
            # leeching_html = result.get('leeching_html')
            if 'greatposterwall' in site.url or 'dicmusic' in site.url:
                try:
                    logger.info(details_html)
                    if details_html.get('status') == 'success' and seeding_html.get('status') == 'success':
                        seeding_response = seeding_html.get('response')
                        mail_str = seeding_response.get("notifications").get("messages")
                        notice_str = seeding_response.get("notifications").get("notifications")
                        my_site.mail = int(mail_str) + int(notice_str)
                        if my_site.mail > 0:
                            template = '### <font color="red">{} 有{}条新短消息，请注意及时查收！</font>  \n'
                            # 测试发送网站消息原内容
                            self.send_text(f'{template.format(site.name, my_site.mail)}\n{mail_str}\n{notice_str}')
                        # ajax.php?action=user&id=
                        details_response = details_html.get('response')
                        stats = details_response.get('stats')
                        downloaded = stats.get('downloaded')
                        uploaded = stats.get('uploaded')
                        ratio = stats.get('ratio').replace(',', '')
                        my_site.time_join = stats.get('joinedDate')
                        my_site.latest_active = stats.get('lastAccess')
                        my_site.my_level = details_response.get('personal').get('class')
                        community = details_response.get('community')
                        my_site.seed = community.get('seeding')
                        my_site.leech = community.get('leeching')
                        # ajax.php?action=index
                        if 'greatposterwall' in site.url:
                            userdata = seeding_response.get('userstats')
                            my_sp = userdata.get('bonusPoints')
                            # if userdata.get('bonusPoints') else 0
                            seeding_size = userdata.get('seedingSize')
                            # if userdata.get('seedingSize') else 0
                            my_site.sp_hour = userdata.get('seedingBonusPointsPerHour')
                            # if userdata.get('seedingBonusPointsPerHour') else 0
                        if 'dicmusic' in site.url:
                            logger.info('海豚')
                            """未取得授权前不开放本段代码，谨防ban号
                            bonus_res = self.send_request(my_site, url=site.url + site.page_seeding, timeout=15)
                            sp_str = self.parse(bonus_res, '//h3[contains(text(),"总积分")]/text()')
                            my_sp = get_decimals(''.join(sp_str))
                            hour_sp_str = self.parse(bonus_res, '//*[@id="bprates_overview"]/tbody/tr/td[3]/text()')
                            my_site.sp_hour = ''.join(hour_sp_str)
                            seeding_size_str = self.parse(bonus_res,
                                                          '//*[@id="bprates_overview"]/tbody/tr/td[2]/text()')
                            seeding_size = FileSizeConvert.parse_2_byte(''.join(seeding_size_str))
                            """
                            my_sp = 0
                            my_site.sp_hour = 0
                            seeding_size = 0
                        my_site.save()
                        res_gpw = SiteStatus.objects.update_or_create(
                            site=my_site,
                            created_at__date__gte=datetime.today(),
                            defaults={
                                'ratio': 'inf' if ratio == '∞' else ratio,
                                'downloaded': downloaded,
                                'uploaded': uploaded,
                                'my_sp': my_sp,
                                'my_bonus': 0,
                                # 做种体积
                                'seed_vol': seeding_size,
                            })
                        if float(ratio) < 1:
                            self.send_request(f'{site.name} 分享率 {ratio} 过低，请注意')
                        return CommonResponse.success(data=res_gpw)
                    else:
                        return CommonResponse.error(data=result)
                except Exception as e:
                    # 打印异常详细信息
                    message = '{} 解析个人主页信息：失败！原因：{}'.format(site.name, e)
                    logger.error(message)
                    logger.error(traceback.format_exc(limit=3))
                    # raise
                    # self.send_text('# <font color="red">' + message + '</font>  \n')
                    return CommonResponse.error(msg=message)
                pass
            else:
                # 获取指定元素
                # title = details_html.xpath('//title/text()')
                # seed_vol_list = seeding_html.xpath(site.record_bulk_rule)
                seed_vol_list = seeding_html.xpath(site.seed_vol_rule)
                if 'lemonhd.org' in site.url:
                    logger.info('做种体积：{}'.format(seed_vol_list))
                    seed_vol_size = ''.join(seed_vol_list).split(':')[-1].strip()
                    seed_vol_all = FileSizeConvert.parse_2_byte(seed_vol_size)
                else:
                    if len(seed_vol_list) > 0 and site.url not in [
                        'https://nextpt.net/'
                    ]:
                        seed_vol_list.pop(0)
                    logger.info('做种数量seeding_vol：{}'.format(len(seed_vol_list)))
                    # 做种体积
                    seed_vol_all = 0
                    for seed_vol in seed_vol_list:
                        # logger.info(etree.tostring(seed_vol))
                        vol = ''.join(seed_vol.xpath('.//text()'))
                        # logger.info(vol)
                        if not len(vol) <= 0:
                            size = FileSizeConvert.parse_2_byte(
                                vol.replace('i', '')  # U2返回字符串为mib，gib
                            )
                            if size:
                                seed_vol_all += size
                            else:
                                msg = '## <font color="red">{} 获取做种大小失败，请检查规则信息是否匹配？</font>'.format(
                                    site.name)
                                logger.warning(msg)
                                self.send_text(msg)
                                break
                        else:
                            # seed_vol_all = 0
                            pass
                logger.info('做种体积：{}'.format(FileSizeConvert.parse_2_file_size(seed_vol_all)))
                # logger.info(''.join(seed_vol_list).strip().split('：'))
                # logger.info(title)
                # logger.info(etree.tostring(details_html))
                # leech = self.get_user_torrent(leeching_html, site.leech_rule)
                # seed = self.get_user_torrent(seeding_html, site.seed_rule)
                logger.info(f'下载数目字符串：{details_html.xpath(site.leech_rule)}')
                logger.info(f'下上传数目字符串：{details_html.xpath(site.seed_rule)}')
                leech = re.sub(r'\D', '', ''.join(details_html.xpath(site.leech_rule)).strip())
                logger.info(f'当前下载数：{leech}')
                seed = ''.join(details_html.xpath(site.seed_rule)).strip()
                logger.info(f'当前做种数：{seed}')
                if not leech and not seed:
                    return CommonResponse.error(
                        status=StatusCodeEnum.WEB_CONNECT_ERR,
                        msg=StatusCodeEnum.WEB_CONNECT_ERR.errmsg + '请检查Cookie是否过期？'
                    )
                # seed = len(seed_vol_list)

                downloaded = ''.join(
                    details_html.xpath(site.downloaded_rule)
                ).replace(':', '').replace('\xa0\xa0', '').replace('i', '').strip(' ')
                uploaded = ''.join(
                    details_html.xpath(site.uploaded_rule)
                ).replace(':', '').replace('i', '').strip(' ')
                if 'hdchina' in site.url:
                    downloaded = downloaded.split('(')[0].replace(':', '').strip()
                    uploaded = uploaded.split('(')[0].replace(':', '').strip()
                downloaded = FileSizeConvert.parse_2_byte(downloaded)
                uploaded = FileSizeConvert.parse_2_byte(uploaded)

                invitation = ''.join(
                    details_html.xpath(site.invitation_rule)
                ).strip(']:').replace('[', '').strip()
                logger.info(f'邀请：{invitation}')
                # invitation = re.sub("\D", "", invitation)
                # time_join_1 = ''.join(
                #     details_html.xpath(site.time_join_rule)
                # ).split('(')[0].strip('\xa0').strip()
                # logger.info('注册时间：', time_join_1)
                # time_join = time_join_1.replace('(', '').replace(')', '').strip('\xa0').strip()
                logger.info(f'注册时间：{details_html.xpath(site.time_join_rule)}')
                time_join = re.findall(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', ''.join(
                    details_html.xpath(site.time_join_rule)
                ).strip())
                my_site.time_join = ''.join(time_join)
                # 去除字符串中的中文
                my_level_1 = ''.join(
                    details_html.xpath(site.my_level_rule)
                ).replace('_Name', '').replace('fontBold', '').strip()
                if 'hdcity' in site.url:
                    my_level = my_level_1.strip()
                # elif 'u2' in site.url:
                #     my_level = ''.join(re.findall(r'/(.*).{4}', my_level_1)).title()
                else:
                    my_level = re.sub(u"([^\u0041-\u005a\u0061-\u007a])", "", my_level_1)
                logger.info('用户等级：{}-{}'.format(my_level_1, my_level))
                # my_level = re.sub('[\u4e00-\u9fa5]', '', my_level_1)
                # logger.info('正则去除中文：', my_level)
                # latest_active = ''.join(
                #     details_html.xpath(site.latest_active_rule)
                # ).strip('\xa0').strip()
                # if '(' in latest_active:
                #     latest_active = latest_active.split('(')[0].strip()

                # 获取字符串中的魔力值
                my_sp = ''.join(
                    details_html.xpath(site.my_sp_rule)
                ).replace(',', '').strip()
                logger.info('魔力：{}'.format(details_html.xpath(site.my_sp_rule)))

                if my_sp:
                    my_sp = get_decimals(my_sp)

                my_bonus_1 = ''.join(
                    details_html.xpath(site.my_bonus_rule)
                ).strip('N/A').replace(',', '').strip()
                if my_bonus_1 != '':
                    my_bonus = get_decimals(my_bonus_1)
                else:
                    my_bonus = 0
                # if '（' in my_bonus:
                #     my_bonus = my_bonus.split('（')[0]

                hr = ''.join(details_html.xpath(site.my_hr_rule)).replace('H&R:', '').strip()

                my_hr = hr if hr else '0'
                logger.info(f'h&r: {hr} ,解析后：{my_hr}')
                # logger.info(my_bonus)
                # 更新我的站点数据
                invitation = converter.convert(invitation)
                # x = invitation.split('/')
                # invitation = re.sub('[\u4e00-\u9fa5]', '', invitation)
                logger.info(f'当前获取邀请数：{invitation}')
                if invitation == '没有邀请资格':
                    my_site.invitation = 0
                elif '/' in invitation:
                    invitation_list = [int(n) for n in invitation.split('/')]
                    # my_site.invitation = int(invitation) if invitation else 0
                    my_site.invitation = sum(invitation_list)
                elif '(' in invitation:
                    invitation_list = [int(get_decimals(n)) for n in invitation.split('(')]
                    # my_site.invitation = int(invitation) if invitation else 0
                    my_site.invitation = sum(invitation_list)
                elif not invitation:
                    my_site.invitation = 0
                else:
                    my_site.invitation = int(re.sub('\D', '', invitation))
                my_site.latest_active = datetime.now()
                my_site.my_level = my_level if my_level != '' else ' '
                if my_hr:
                    my_site.my_hr = my_hr
                my_site.seed = int(get_decimals(seed)) if seed else 0
                logger.info(f'当前下载数：{leech}')
                my_site.leech = int(get_decimals(leech)) if leech else 0

                logger.info('站点：{}'.format(site))
                logger.info('等级：{}'.format(my_level))
                logger.info('魔力：{}'.format(my_sp))
                logger.info('积分：{}'.format(my_bonus if my_bonus else 0))
                # logger.info('分享率：{}'.format(ratio))
                logger.info('下载量：{}'.format(downloaded))
                logger.info('上传量：{}'.format(uploaded))
                logger.info('邀请：{}'.format(invitation))
                # logger.info('注册时间：{}'.format(time_join))
                # logger.info('最后活动：{}'.format(latest_active))
                logger.info('H&R：{}'.format(my_hr))
                logger.info('上传数：{}'.format(seed))
                logger.info('下载数：{}'.format(leech))
                try:
                    ratio = ''.join(
                        details_html.xpath(site.ratio_rule)
                    ).lower().replace(',', '').replace('无限', 'inf').replace('∞', 'inf'). \
                        replace('inf.', 'inf').replace(
                        'null', 'inf').replace('---', 'inf').replace('-', 'inf').replace('\xa0', '').strip(
                        ']:').strip('：').strip()
                    if not ratio:
                        ratio = ''.join(
                            details_html.xpath('//font[@class="color_ratio"][1]/following-sibling::font[1]/text()[1]'))
                    if ratio.count('上传量') > 0 and site.url == 'https://totheglory.im/':
                        # 适配TTG inf分享率
                        ratio = ''.join(
                            details_html.xpath(
                                '//font[contains(text(),"分享率 ")][1]/following-sibling::text()[1]')) \
                            .replace('\xa0', '').replace('.', '').strip()
                    # 分享率告警通知
                    logger.info('ratio：{}'.format(ratio))
                    if ratio and ratio != 'inf' and float(ratio) <= 1:
                        message = '# <font color="red">' + site.name + ' 站点分享率告警：' + str(ratio) + '</font>  \n'
                        self.send_text(message)
                    # 检查邮件
                    mail_str = ''.join(details_html.xpath(site.mailbox_rule))
                    notice_str = ''.join(details_html.xpath(site.notice_rule))
                    if mail_str or notice_str:
                        mail_count = re.sub(u"([^\u0030-\u0039])", "", mail_str)
                        notice_count = re.sub(u"([^\u0030-\u0039])", "", notice_str)
                        mail_count = int(mail_count) if mail_count else 0
                        notice_count = int(notice_count) if notice_count else 0
                        my_site.mail = mail_count + notice_count
                        if mail_count + notice_count > 0:
                            template = '### <font color="red">{} 有{}条新短消息，请注意及时查收！</font>  \n'
                            # 测试发送网站消息原内容
                            self.send_text(
                                f'{template.format(site.name, mail_count + notice_count)}\n{mail_str}\n{notice_str}'
                            )
                    else:
                        my_site.mail = 0
                    if site.url in [
                        'https://nextpt.net/',
                    ]:
                        # logger.info(site.hour_sp_rule)
                        res_sp_hour_list = details_html.xpath(site.hour_sp_rule)
                        # logger.info(details_html)
                        # logger.info(res_sp_hour_list)
                        res_sp_hour = ''.join(res_sp_hour_list)
                        my_site.sp_hour = get_decimals(res_sp_hour)
                        # 飞天邀请获取
                        logger.info(f'邀请页面：{site.url}Invites')
                        res_next_pt_invite = self.send_request(my_site, f'{site.url}Invites')
                        logger.info(res_next_pt_invite.text)
                        str_next_pt_invite = ''.join(self.parse(
                            res_next_pt_invite,
                            site.invitation_rule))
                        print(f'邀请字符串：{str_next_pt_invite}')
                        list_next_pt_invite = re.findall('\d+', str_next_pt_invite)
                        print(list_next_pt_invite)
                        my_site.invitation = int(list_next_pt_invite[0]) - int(list_next_pt_invite[1])
                    else:
                        res_sp_hour = self.get_hour_sp(my_site=my_site)
                        if res_sp_hour.code != StatusCodeEnum.OK.code:
                            logger.error(my_site.site.name + res_sp_hour.msg)
                        else:
                            my_site.sp_hour = res_sp_hour.data
                    # 保存上传下载等信息
                    my_site.save()
                    # 外键反向查询
                    # status = my_site.sitestatus_set.filter(updated_at__date__gte=datetime.datetime.today())
                    # logger.info(status)
                    result = SiteStatus.objects.update_or_create(
                        site=my_site, created_at__date__gte=datetime.today(),
                        defaults={
                            'ratio': float(ratio) if ratio else 0,
                            'downloaded': int(downloaded),
                            'uploaded': int(uploaded),
                            'my_sp': float(my_sp),
                            'my_bonus': float(
                                my_bonus) if my_bonus != '' else 0,
                            # 做种体积
                            'seed_vol': seed_vol_all,
                        })
                    # logger.info(result) # result 本身就是元祖
                    return CommonResponse.success(data=result)
                except Exception as e:
                    # 打印异常详细信息
                    message = '{} 解析个人主页信息：失败！原因：{}'.format(my_site.site.name, e)
                    logger.error(message)
                    logger.error(traceback.format_exc(limit=3))
                    # raise
                    # self.send_text('# <font color="red">' + message + '</font>  \n')
                    return CommonResponse.error(msg=message)

    def get_hour_sp(self, my_site: MySite):
        """获取时魔"""
        site = my_site.site
        try:
            response = self.send_request(
                my_site=my_site,
                url=site.url + site.page_mybonus,
            )
            # print(response.text.encode('utf8'))
            """
            if 'btschool' in site.url:
                # logger.info(response.text.encode('utf8'))
                url = self.parse(response, '//form[@id="challenge-form"]/@action[1]')
                data = {
                    'md': ''.join(self.parse(response, '//form[@id="challenge-form"]/input[@name="md"]/@value')),
                    'r': ''.join(self.parse(response, '//form[@id="challenge-form"]/input[@name="r"]/@value'))
                }
                logger.info(data)
                logger.info('学校时魔页面url：', url)
                response = self.send_request(
                    my_site=my_site,
                    url=site.url + ''.join(url).lstrip('/'),
                    method='post',
                    # headers=headers,
                    data=data,
                    delay=60
                )
                """
            res = converter.convert(response.content)
            # logger.info('时魔响应：{}'.format(response.text))
            # logger.info('转为简体的时魔页面：', str(res))
            # res_list = self.parse(res, site.hour_sp_rule)
            res_list = etree.HTML(res).xpath(site.hour_sp_rule)
            if 'u2.dmhy.org' in site.url:
                res_list = ''.join(res_list).split('，')
                res_list.reverse()
            logger.info('时魔字符串：{}'.format(res_list))
            if len(res_list) <= 0:
                CommonResponse.error(msg='时魔获取失败！')
            return CommonResponse.success(
                data=get_decimals(res_list[0].replace(',', ''))
            )
        except Exception as e:
            # 打印异常详细信息
            message = '{} 时魔获取失败！{}'.format(site.name, e)
            logger.error(message)
            logger.error(traceback.format_exc(limit=3))
            return CommonResponse.success(
                msg=message,
                data=0
            )
