# -*- coding: utf-8 -*-
# Generated by Django 1.9.2 on 2016-08-29 11:39
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_eventsettings_report_footer'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='product',
            options={'ordering': ('-priority', 'pk')},
        ),
        migrations.AddField(
            model_name='product',
            name='priority',
            field=models.IntegerField(default=0, help_text='Will be used for sorting, high priorities come first.', verbose_name='Priority'),
        ),
        migrations.AlterField(
            model_name='eventsettings',
            name='report_footer',
            field=models.CharField(default='CCC Veranstaltungsgesellschaft mbH', help_text='This will show up on backoffice session reports.', max_length=500),
        ),
    ]
