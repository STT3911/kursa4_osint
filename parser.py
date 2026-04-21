import asyncio
import os
import sqlite3
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError 

api_id = 
api_hash = ''

client = TelegramClient('osint_session', api_id, api_hash)
os.makedirs('avatars', exist_ok=True)

conn = sqlite3.connect('osint_database.db')
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS profiles (user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT, bio TEXT, photo_path TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, group_name TEXT, parsed_at TIMESTAMP, UNIQUE(user_id, group_name))''')
conn.commit()

async def main():
    await client.start()
    target_groups = ['rabota_chaty1'] 
    
    limit_new_users = 400
    
    cursor.execute('SELECT user_id FROM profiles')
    existing_users = {row[0] for row in cursor.fetchall()}
    print(f"🗄 В базе уже есть {len(existing_users)} уникальных профилей.")
    
    print(f"{limit_new_users} НОВЫХ профилей.")
    
    for group in target_groups:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🕵️‍♂️ Анализируем группу: @{group}...")
        new_count = 0
        skipped_count = 0
        
        try:
            async for user in client.iter_participants(group):
                
                if user.id in existing_users:
                    skipped_count += 1
                    continue 
                
                new_count += 1
                bio = ""
                
                try:
                    full_user = await client(GetFullUserRequest(id=user))
                    bio = full_user.full_user.about or ""
                except FloodWaitError as e:
                    print(f"\n Telegram просит паузу {e.seconds} секунд...")
                    await asyncio.sleep(e.seconds)
                    new_count -= 1 
                    continue 
                except Exception:
                    pass
                
                photo_path = ""
                if user.photo:
                    photo_path = f'avatars/{user.id}.jpg'
                    if not os.path.exists(photo_path):
                        try:
                            await client.download_profile_photo(user, file=photo_path)
                        except FloodWaitError as e:
                            print(f"\nЛимит на фото. Засыпаем на {e.seconds} сек...")
                            await asyncio.sleep(e.seconds)
                
                cursor.execute('INSERT OR REPLACE INTO profiles VALUES (?, ?, ?, ?, ?)', 
                               (user.id, user.first_name, user.username, bio, photo_path))
                
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute('INSERT OR IGNORE INTO user_groups (user_id, group_name, parsed_at) VALUES (?, ?, ?)', 
                               (user.id, group, current_time))
                conn.commit()
                
                existing_users.add(user.id)
                
                print(f"\rтолько новые в @{group}: {new_count}/{limit_new_users}  старых: {skipped_count}", end="")
                
                if new_count >= limit_new_users:
                    print("\n  лимит новых пользователей для этой группы!")
                    break 
                
                await asyncio.sleep(1.5)
                
        except Exception as e:
            print(f"\n Не удалось обработать @{group}: {e}")
            
        print(f"\n@{group} завершена.")

    print("\cбор завершен")

if __name__ == '__main__':
    asyncio.run(main())