
def all_subjects():
    """Return a de-duplicated, alphabetically sorted list of every subject
    used across all classes. Used to populate subject datalists."""
    collected = set()
    for class_name in (
        'Creche', 'KG', 'Nursery 1', 'Nursery 2',
        'Basic 1', 'Basic 2', 'Basic 3', 'Basic 4', 'Basic 5',
        'JSS1', 'JSS2', 'JSS3', 'SS1', 'SS2', 'SS3',
    ):
        collected.update(get_subjects_for_class(class_name))
    for department in ('Science', 'Arts', 'Commercial'):
        collected.update(get_subjects_for_class('SS1', department))
    return sorted(collected)


def get_subjects_for_class(class_name, department=None):
    """
    Returns a list of subjects for a given class and department.
    """
    if not class_name:
        return []
    class_name = class_name.upper()

    # Creche - Using same subjects as KG
    if class_name == 'CRECHE':
        return [
            'Numeracy',
            'Literacy',
            'Bible Knowledge',
            'Health Habit',
            'Moral Habit',
            'Science',
            'Oral Drill',
            'Rhymes',
            'Penmanship',
            'Sensorial',
            'Creative Art',
            'Social Habit'
        ]

    # Kindergarten (KG)
    elif class_name == 'KG':
        return [
            'Numeracy',
            'Literacy',
            'Bible Knowledge',
            'Health Habit',
            'Moral Habit',
            'Science',
            'Oral Drill',
            'Rhymes',
            'Penmanship',
            'Sensorial',
            'Creative Art',
            'Social Habit'
        ]

    # Nursery 1
    elif class_name == 'NURSERY 1' or class_name == 'NURSERY1':
        return [
            'Numeracy',
            'Literacy',
            'Quantitative',
            'Verbal',
            'CRK',
            'Rhyme',
            'Creative Art',
            'Hand Writing',
            'Health Habits',
            'Social Habits',
            'Basic Science',
            'Food & Nutrition',
            'Civic Education'
        ]

    # Nursery 2
    elif class_name == 'NURSERY 2' or class_name == 'NURSERY2':
        return [
            'Mathematics',
            'English Language',
            'Basic Science',
            'Social Studies',
            'Civic Education',
            'History',
            'Health Education',
            'CRS',
            'Creative Art',
            'Literature',
            'Computer',
            'Handwriting',
            'Verbal',
            'Quantitative',
            'Yoruba',
            'Diction'
        ]

    # Basic 1
    elif class_name == 'BASIC 1' or class_name == 'BASIC1':
        return [
            'Mathematics',
            'English Language',
            'Basic Science',
            'Social Studies',
            'Civic Education',
            'History',
            'Health Education',
            'CRS',
            'Creative Art',
            'Literature',
            'Computer',
            'Handwriting',
            'Verbal',
            'Quantitative',
            'Yoruba',
            'Diction'
        ]

    # Basic 2
    elif class_name == 'BASIC 2' or class_name == 'BASIC2':
        return [
            'Mathematics',
            'PHE',
            'English',
            'Diction',
            'RNV',
            'CCA',
            'History',
            'Literature',
            'Penmanship',
            'Computer',
            'CRS',
            'Yoruba'
        ]

    # Basic 3, 4, 5
    elif class_name in ['BASIC 3', 'BASIC3', 'BASIC 4', 'BASIC4', 'BASIC 5', 'BASIC5']:
        return [
            'Mathematics',
            'PHE',
            'English',
            'Diction',
            'Pre Vocational',
            'RNV',
            'CCA',
            'History',
            'Literature',
            'Penmanship',
            'Computer',
            'CRS',
            'Yoruba'
        ]

    # Junior Secondary School (JSS1-JSS3)
    elif class_name.startswith('JSS'):
        subjects = [
            'English Language',
            'Mathematics',
            'Basic Science',
            'Basic Technology',
            'Social Studies',
            'Civic Education',
            'Computer Studies',
            'Physical and Health Education',
            'Home Economics',
            'Agricultural Science',
            'Business Studies',
            'Christian Religious Studies',
            'Yoruba',
            'Social Studies',
        ]
        return subjects
    
    # Senior Secondary School (SS1-SS3)
    elif class_name.startswith('SS'):
        # General subjects for all SS students
        general_subjects = [
            'English Language',
            'Mathematics',
            'Civic Education',
            'Computer Studies',
            'Economics',
            'Biology',
            'Agricultural Science',
            'Marketing',
            'Further Mathematics',
        ]

        # Department-specific subjects
        if department and department.upper() == 'SCIENCE':
            return general_subjects + [
                'Physics',
                'Chemistry'
            ]
        elif department and department.upper() == 'ARTS':
            return general_subjects + [
                'Literature in English',
                'Government',
                'Christian Religious Studies'
            ]
        elif department and department.upper() == 'COMMERCIAL':
            return general_subjects + [
                'Commerce',
                'Accounting',
                'Government',
            ]
        else:
            # If no department specified, return all subjects
            return general_subjects + [
                'Physics',
                'Chemistry',
                'Biology',
                'Further Mathematics',
                'Literature in English',
                'Government',
                'Christian Religious Studies',
                'Islamic Religious Studies',
                'History',
                'Commerce',
                'Accounting',
                'Economics',
                'Marketing'
            ]

    # Default subjects for any other class
    else:
        return [
            'English Language',
            'Mathematics',
            'Basic Science',
            'Social Studies',
            'Civic Education',
            'Basic Technology',
            'Computer Studies',
            'Physical and Health Education'
        ]
