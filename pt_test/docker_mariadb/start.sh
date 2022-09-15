#!/bin/bash
# 升级pip到最新
python -m pip install --upgrade pip
service mariadb start
CONTAINER_ALREADY_STARTED="CONTAINER_ALREADY_STARTED_PLACEHOLDER"
if [ ! -e $CONTAINER_ALREADY_STARTED ]; then
  echo "-- First container startup --"
  # 此处插入你要执行的命令或者脚本文件
  git config --global init.defaultBranch master &&
#    git init &&
#    git remote add origin https://gitee.com/ngfchl/ptools &&
    # 设置拉取最新文件并覆盖
#    git config pull.ff only &&
#    git pull
#  git checkout master &&
#    git branch --set-upstream-to=origin/master master
  mysqladmin -u root password $MARIADB_ROOT_PASSWORD &&
    mysqladmin -u root -p$MARIADB_ROOT_PASSWORD create main &&
    pip install -r requirements.txt -U &&
    python manage.py makemigrations &&
    python manage.py migrate &&
    python manage.py loaddata pt.json
  touch $CONTAINER_ALREADY_STARTED
  # 创建超级用户
  DJANGO_SUPERUSER_USERNAME=$DJANGO_SUPERUSER_USERNAME \
    DJANGO_SUPERUSER_EMAIL=$DJANGO_SUPERUSER_EMAIL \
    DJANGO_SUPERUSER_PASSWORD=$DJANGO_SUPERUSER_PASSWORD \
    python manage.py createsuperuser --noinput
else
  echo "-- Not first container startup --"

fi
pip install -r requirements.txt -U &&
  python manage.py makemigrations &&
  python manage.py migrate &&
  python manage.py runserver 0.0.0.0:$DJANGO_WEB_PORT --noreload
