from app import create_app
from extensions import db
from models import Class

app = create_app()
with app.app_context():
    # Default classes to add
    default_classes = [
        'Creche',
        'KG',
        'Nursery 1',
        'Nursery 2',
        'Basic 1',
        'Basic 2',
        'Basic 3',
        'Basic 4',
        'Basic 5',
        'JSS1',
        'JSS2',
        'JSS3',
        'SS1',
        'SS2',
        'SS3'
    ]
    
    added_count = 0
    for class_name in default_classes:
        existing_class = Class.query.filter_by(class_name=class_name).first()
        if not existing_class:
            cls = Class(class_name=class_name)
            db.session.add(cls)
            added_count += 1
            print(f"Added: {class_name}")
        else:
            print(f"Already exists: {class_name}")
    
    db.session.commit()
    print(f"\nTotal classes added: {added_count}")
    print(f"Total classes in database: {Class.query.count()}")
