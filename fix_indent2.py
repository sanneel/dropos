"""Add 4 spaces to every line from line 746 to end of init_db (line ~921)."""
lines = open('backend/database.py', 'r', encoding='utf-8').readlines()
# Line 746 is index 745; it's the first line of the transaction body
# The init_db function ends at the end of the file (line 921 = index 920)
start = 745  # index of first line after 'async with conn.transaction():'
end = len(lines)

for i in range(start, end):
    if lines[i].strip():           # skip blank lines
        lines[i] = '    ' + lines[i]

open('backend/database.py', 'w', encoding='utf-8').writelines(lines)
print(f"Indented lines {start+1}–{end}. Total lines: {len(lines)}")
