from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import trusts.zero.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('trusts', '0002_trustgroup'),
        ('auth', '0006_require_contenttypes_0002'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Organization',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=40)),
                ('manager', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='managed_organizations',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=40)),
                ('trust', models.ForeignKey(
                    default=1,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='trusts_zero_tests_category_content',
                    to='trusts.trust',
                )),
            ],
            options={
                'default_permissions': ('add', 'read', 'change', 'delete'),
                'permissions': (('add_topic_to_category', 'Add topic to a category'),),
            },
            bases=(trusts.zero.models.ReadonlyFieldsMixin, models.Model),
        ),
        migrations.CreateModel(
            name='TestGroupJunction',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=40)),
                ('content', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='auth.group',
                    unique=True,
                )),
                ('trust', models.ForeignKey(
                    default=1,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='trusts_zero_tests_testgroupjunction',
                    to='trusts.trust',
                )),
            ],
            options={
                'default_permissions': (),
            },
            bases=(trusts.zero.models.ReadonlyFieldsMixin, models.Model),
        ),
        migrations.AlterUniqueTogether(
            name='testgroupjunction',
            unique_together={('content',)},
        ),
        migrations.CreateModel(
            name='Ticket',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=40)),
                ('status', models.CharField(default='open', max_length=20)),
                ('region', models.CharField(blank=True, max_length=40, null=True)),
                ('organization', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='tickets',
                    to='trusts_zero_tests.organization',
                )),
                ('owner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='zero_tickets',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('trust', models.ForeignKey(
                    default=1,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='trusts_zero_tests_ticket_content',
                    to='trusts.trust',
                )),
            ],
            options={
                'default_permissions': ('add', 'read', 'change', 'delete'),
            },
            bases=(trusts.zero.models.ReadonlyFieldsMixin, models.Model),
        ),
    ]
