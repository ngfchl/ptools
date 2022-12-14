# Generated by Django 4.1.2 on 2022-11-25 18:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auto_pt', '0004_alter_taskjob_job_id_alter_taskjob_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='taskjob',
            name='replace_existing',
            field=models.BooleanField(default=True, editable=False, help_text='不设置此项重启项目后会报任务id已存在的错误, 设置此参数后会对已有的任务进行覆盖', verbose_name='覆盖任务'),
        ),
    ]
