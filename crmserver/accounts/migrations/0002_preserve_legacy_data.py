from django.db import migrations


def preserve_legacy_data(apps, schema_editor):
    alias = schema_editor.connection.alias
    models = [apps.get_model(app, model) for app, model in
              [('customers', 'Customer'), ('deals', 'Deal'), ('tasks', 'Task')]]
    if any(model.objects.using(alias).filter(organization__isnull=True).exists() for model in models):
        organization = apps.get_model('accounts', 'Organization').objects.using(alias).create(name='Данные до v0.5')
        for model in models:
            model.objects.using(alias).filter(organization__isnull=True).update(organization_id=organization.pk)
    # No users are attached automatically: legacy data has no verified owner.


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
        ('customers', '0002_organization'),
        ('deals', '0002_organization'),
        ('tasks', '0002_organization'),
    ]
    operations = [migrations.RunPython(preserve_legacy_data, migrations.RunPython.noop)]
