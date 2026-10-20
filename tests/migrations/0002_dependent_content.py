import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trusts', '0002_trustgroup'),
        ('trusts_zero_tests', '0001_test_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='Receipt',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=40)),
                ('trust', models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, related_name='trusts_zero_tests_receipt_content', to='trusts.trust')),
            ],
        ),
        migrations.CreateModel(
            name='OrphanDoc',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=40)),
                ('receipt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='orphan', to='trusts_zero_tests.receipt')),
            ],
        ),
        migrations.CreateModel(
            name='ReceiptImage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=40)),
                ('receipt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='image', to='trusts_zero_tests.receipt')),
            ],
        ),
        migrations.CreateModel(
            name='ReceiptImageMeta',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=40)),
                ('image', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='image', to='trusts_zero_tests.receiptimage')),
            ],
        ),
    ]
