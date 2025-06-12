import os
import sys

# --- КОНФИГУРАЦИЯ ---
CONFIG_FILE = 'config.txt'


# --- ЧТЕНИЕ И ЗАПИСЬ ФАЙЛА НАСТРОЕК ---
def load_config():
    """Загружает конфигурацию из файла config.txt. Создает его, если он не существует."""
    config_data = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file_path = os.path.join(script_dir, CONFIG_FILE)

    if not os.path.exists(config_file_path):
        print(f"Файл настроек '{config_file_path}' не найден. Создаю новый файл.")
        try:
            with open(config_file_path, 'w', encoding='utf-8') as f:
                f.write("REACTIVE_AUTH_COOKIE=\n")
                f.write("SETUP_COMPLETE=False\n")
                f.write("MODEL_CREATED_COMPLETE=False\n")
                f.write("DRIVER_INSTALL_SUGGESTED=False\n")  # НОВЫЙ ФЛАГ
            print(f"Файл '{config_file_path}' успешно создан.")
        except Exception as e:
            print(f"Критическая ошибка при создании файла '{config_file_path}': {e}")
            sys.exit(1)

    try:
        with open(config_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    config_data[key.strip()] = value.strip()

        # Убедимся, что все необходимые флаги есть
        if 'REACTIVE_AUTH_COOKIE' not in config_data:
            config_data['REACTIVE_AUTH_COOKIE'] = ''
            with open(config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nREACTIVE_AUTH_COOKIE=\n")

        if 'SETUP_COMPLETE' not in config_data:
            config_data['SETUP_COMPLETE'] = 'False'
            with open(config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nSETUP_COMPLETE=False\n")

        if 'MODEL_CREATED_COMPLETE' not in config_data:
            config_data['MODEL_CREATED_COMPLETE'] = 'False'
            with open(config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nMODEL_CREATED_COMPLETE=False\n")

        if 'DRIVER_INSTALL_SUGGESTED' not in config_data:  # Проверка нового флага
            config_data['DRIVER_INSTALL_SUGGESTED'] = 'False'
            with open(config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nDRIVER_INSTALL_SUGGESTED=False\n")

        return config_data
    except Exception as e:
        print(f"Критическая ошибка при чтении файла '{config_file_path}': {e}")
        sys.exit(1)


def save_config(config_data):
    """Сохраняет весь словарь конфигурации в config.txt."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file_path = os.path.join(script_dir, CONFIG_FILE)
    try:
        with open(config_file_path, 'w', encoding='utf-8') as f:
            for key, value in config_data.items():
                f.write(f"{key}={value}\n")
        print(f"Конфигурация сохранена в '{config_file_path}'.")
    except Exception as e:
        print(f"ОШИБКА: Не удалось сохранить конфигурацию в '{config_file_path}': {e}")
