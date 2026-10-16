from catalog.models import Attribute, ProductType


PRESETS = {
    'Цветы': [('Вид', 'text', []), ('Сорт', 'text', []),
              ('Цвет', 'choice', ['Белый', 'Розовый', 'Красный', 'Жёлтый', 'Фиолетовый', 'Другой']),
              ('Высота, см', 'number', [])],
    'Букеты': [('Состав', 'text', []), ('Количество цветов', 'number', []),
               ('Повод', 'choice', ['День рождения', 'Свадьба', 'Признание', 'Без повода']),
               ('Основной цвет', 'text', [])],
    'Семена цветов': [('Вид', 'text', []), ('Сорт', 'text', []),
                      ('Жизненный цикл', 'choice', ['Однолетние', 'Двулетние', 'Многолетние']),
                      ('Количество семян', 'number', []), ('Период посева', 'text', [])],
}


def create_presets(storefront):
    for name, attributes in PRESETS.items():
        product_type = ProductType.objects.create(storefront=storefront, name=name)
        Attribute.objects.bulk_create([
            Attribute(product_type=product_type, name=label, kind=kind, options=options, position=i)
            for i, (label, kind, options) in enumerate(attributes)
        ])
