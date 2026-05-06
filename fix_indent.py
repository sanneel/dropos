lines = open('backend/database.py', 'r', encoding='utf-8').readlines()
start_body = 743
end_body = len(lines)
for i in range(742, len(lines)):
    if lines[i].startswith('async def ') or (lines[i].startswith('def ') and not lines[i].startswith(' ')):
        end_body = i
        break
for i in range(start_body, end_body):
    if lines[i].strip():
        lines[i] = '    ' + lines[i]
open('backend/database.py', 'w', encoding='utf-8').writelines(lines)
print('Done, end_body was', end_body)
