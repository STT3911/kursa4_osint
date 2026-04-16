import sqlite3

conn = sqlite3.connect('osint_database.db')
cursor = conn.cursor()

cursor.execute('''
    SELECT p.first_name, p.username, ug.group_name, ug.parsed_at
    FROM profiles p
    JOIN user_groups ug ON p.user_id = ug.user_id
''')

results = cursor.fetchall()

print(f"Связи пользователей с чатами (Найдено записей: {len(results)})\n" + "="*50)

for row in results:
    name = row[0]
    username = f"@{row[1]}" if row[1] else "[Скрыт]"
    group = row[2]
    time = row[3]
    
    print(f"{name} ({username})")
    print(f"Найден в чате: @{group}")
    print(f"Время сбора: {time}")
    print("-" * 50)

conn.close()