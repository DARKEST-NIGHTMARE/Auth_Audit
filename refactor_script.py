import os
import re
import shutil

BASE_DIR = "security_app/lib"

# Define the new structure
file_mapping = {
    # Core
    "main.dart": "main.dart",
    "theme.dart": "core/theme/theme.dart",
    "widgets/glass_card.dart": "core/widgets/glass_card.dart",
    "services/api_service.dart": "core/network/api_service.dart",

    # Features: Auth
    "providers/auth_provider.dart": "features/auth/providers/auth_provider.dart",
    "screens/login_screen.dart": "features/auth/screens/login_screen.dart",
    "screens/register_screen.dart": "features/auth/screens/register_screen.dart",

    # Features: Dashboard
    "screens/dashboard_screen.dart": "features/dashboard/screens/dashboard_screen.dart",

    # Features: Employees
    "models/employee.dart": "features/employees/models/employee.dart",
    "screens/employee_screen.dart": "features/employees/screens/employee_screen.dart",

    # Features: System Users
    "models/system_user.dart": "features/system_users/models/system_user.dart",
    "screens/system_user_screen.dart": "features/system_users/screens/system_user_screen.dart",

    # Features: Security
    "models/security.dart": "features/security/models/security.dart",
    "services/security_service.dart": "features/security/services/security_service.dart",
    "screens/security_dashboard_screen.dart": "features/security/screens/security_dashboard_screen.dart",
    "screens/my_security_screen.dart": "features/security/screens/my_security_screen.dart",
    "screens/session_management_screen.dart": "features/security/screens/session_management_screen.dart",

    # Features: Drive Integration
    "models/drive_item.dart": "features/drive_integration/models/drive_item.dart",
    "models/summarization.dart": "features/drive_integration/models/summarization.dart",
    "services/google_drive_service.dart": "features/drive_integration/services/google_drive_service.dart",
    "services/summarization_service.dart": "features/drive_integration/services/summarization_service.dart",
    "screens/google_drive_screen.dart": "features/drive_integration/screens/google_drive_screen.dart",
}

reverse_mapping = {old: new for old, new in file_mapping.items()}

def get_relative_import(from_file, to_file):
    from_dir = os.path.dirname(from_file)
    rel_path = os.path.relpath(to_file, from_dir)
    return rel_path.replace("\\", "/")

def process_imports():
    # Cache content so we don't read halfway written files or miss moved files
    contents = {}
    for old_path in file_mapping.keys():
        abs_old = os.path.join(BASE_DIR, old_path)
        if os.path.exists(abs_old):
            with open(abs_old, 'r', encoding='utf-8') as f:
                contents[old_path] = f.read()

    for old_path, new_path in file_mapping.items():
        if old_path not in contents:
            continue
            
        content = contents[old_path]

        def replacer(match):
            import_str = match.group(1)
            
            if import_str.startswith('package:security_app/'):
                imported_file = import_str.replace('package:security_app/', '')
                if imported_file in reverse_mapping:
                    return f"import 'package:security_app/{reverse_mapping[imported_file]}';"
                return match.group(0)
            
            if not import_str.startswith('package:') and not import_str.startswith('dart:'):
                from_dir = os.path.dirname(old_path)
                normalized_import = os.path.normpath(os.path.join(from_dir, import_str)).replace("\\", "/")
                
                if normalized_import in reverse_mapping:
                    new_target = reverse_mapping[normalized_import]
                    new_rel_import = get_relative_import(new_path, new_target)
                    if not new_rel_import.startswith('.'):
                        new_rel_import = './' + new_rel_import
                    return f"import '{new_rel_import}';"
                    
            return match.group(0)

        new_content = re.sub(r"import\s+'([^']+)'\s*;", replacer, content)
        new_content = re.sub(r'import\s+"([^"]+)"\s*;', replacer, new_content)

        abs_new_path = os.path.join(BASE_DIR, new_path)
        os.makedirs(os.path.dirname(abs_new_path), exist_ok=True)
        
        with open(abs_new_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

if __name__ == "__main__":
    process_imports()
    
    # We must delete the old files that were moved (but keep main.dart)
    old_dirs = ["models", "providers", "screens", "services", "widgets"]
    for d in old_dirs:
        path = os.path.join(BASE_DIR, d)
        if os.path.exists(path):
            shutil.rmtree(path)
            
    # Remove old theme.dart if it exists and new path is different
    old_theme = os.path.join(BASE_DIR, "theme.dart")
    if os.path.exists(old_theme):
        os.remove(old_theme)
