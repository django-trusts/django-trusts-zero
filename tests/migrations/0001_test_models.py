from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('trusts', '0002_trustgroup'),
        ('auth', '0006_require_contenttypes_0002'),
    ]

    operations = [
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
            },
        ),
        migrations.CreateModel(
            name='Ticket',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=40)),
                ('owner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='zero_tickets',
                    to='auth.user',
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
        ),
    ]
