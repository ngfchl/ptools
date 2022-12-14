# myproject/Dockerfile

# 建立 python3.9 环境
FROM python:3.9.14-slim

# 镜像作者大江狗
MAINTAINER ngfchl ngfchl@126.com

# 设置 python 环境变量
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SUPERUSER_USERNAME=admin
ENV DJANGO_SUPERUSER_EMAIL=admin@eamil.com
ENV DJANGO_SUPERUSER_PASSWORD=adminadmin
ENV DJANGO_WEB_PORT=8000
ENV DEV=master
# 写入pip国内源
COPY pip.conf /root/.pip/pip.conf
# 更新pip版本，更换USTC源，并安装git
RUN /usr/local/bin/python -m pip install --upgrade pip; \
    sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list; \
    apt update && yes|apt install git; \
    apt-get autoclean && rm -rf /var/lib/apt/lists/*
# 创建 ptools 文件夹
RUN mkdir -p /ptools
#RUN git clone https://gitee.com/ngfchl/ptools /ptools
# 将 ptools 文件夹为工作目录
WORKDIR /ptools
# 将当前目录加入到工作目录中（. 表示当前目录）
ADD . /ptools
# 给start.sh可执行权限，并安装依赖
RUN chmod +x /ptools/start.sh && rm -rf /ptools/db/* && pip install -r requirements.txt --no-cache-dir
# 暴露数据库文件夹
VOLUME ["/ptools/db"]
# 暴露访问端口
EXPOSE  $DJANGO_WEB_PORT
# 执行启动文件
ENTRYPOINT ["/bin/bash", "/ptools/start.sh"]