import sys

def patch_app_js(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        target = "onerror=\"this.style.display='none';this.nextElementSibling.style.display='flex'\""
        replacement = "onerror=\"this.style.display='none';this.nextElementSibling.style.display='flex';this.nextElementSibling.innerHTML='IMAGE ERROR'\""
        
        content = content.replace(target, replacement)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Patched {filepath}')
    except Exception as e:
        print(f'Failed to patch {filepath}: {e}')

patch_app_js('frontend/assets/app.js')
patch_app_js('backend/frontend/assets/app.js')
