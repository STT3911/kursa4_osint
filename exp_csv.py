import sqlite3
import csv

def export_db_to_csv():
    conn = sqlite3.connect('osint_database.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT p.user_id, p.first_name, p.username, p.bio, p.photo_path, ug.group_name
        FROM profiles p
        LEFT JOIN user_groups ug ON p.user_id = ug.user_id
        GROUP BY p.user_id
    ''')
    rows = cursor.fetchall()

    column_names = [description[0] for description in cursor.description]

    csv_filename = 'nlp_dataset.csv'
    with open(csv_filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';') # Разделитель точка с запятой для удобства Excel
        
        writer.writerow(column_names)
        
        writer.writerows(rows)

    print(f"выгружено {len(rows)} профилей в файл {csv_filename}")
    conn.close()

if __name__ == '__main__':
    export_db_to_csv()