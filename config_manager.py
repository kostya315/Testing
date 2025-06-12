import os
import sys

# --- КОНФИГУРАЦИЯ ---
USER_CONFIG_FILE = 'config.txt'  # Файл для пользовательских настроек
APP_CONFIG_FILE = 'app_config.txt'  # Файл для настроек приложения


# --- ЧТЕНИЕ И ЗАПИСЬ ФАЙЛА НАСТРОЕК ---
def load_config():
    """
    Загружает конфигурацию из файлов config.txt и app_config.txt.
    Создает их, если они не существуют, и добавляет отсутствующие поля.
    Возвращает объединенный словарь конфигурации.
    """
    config_data = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # --- Загрузка и управление USER_CONFIG_FILE (config.txt) ---
    user_config_file_path = os.path.join(script_dir, USER_CONFIG_FILE)

    if not os.path.exists(user_config_file_path):
        print(f"Файл пользовательских настроек '{user_config_file_path}' не найден. Создаю новый файл.")
        try:
            with open(user_config_file_path, 'w', encoding='utf-8') as f:
                f.write("CAM_FPS=60\n")  # Стандартное значение CAM_FPS
                f.write("CROSS_FADE_ENABLED=True\n")
                f.write("BOUNCING_ENABLED=True\n")
            print(f"Файл '{user_config_file_path}' успешно создан.")
        except Exception as e:
            print(f"Критическая ошибка при создании файла '{user_config_file_path}': {e}")
            sys.exit(1)

    try:
        with open(user_config_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line:
                    key, value = line.split('=', 1)
                    config_data[key.strip()] = value.strip()

        # Проверка и добавление новых полей в пользовательский конфиг, если они отсутствуют
        if 'CAM_FPS' not in config_data:
            config_data['CAM_FPS'] = '60'
            with open(user_config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nCAM_FPS=60\n")
            print("Добавлена настройка 'CAM_FPS=60' в config.txt")

        if 'CROSS_FADE_ENABLED' not in config_data:
            config_data['CROSS_FADE_ENABLED'] = 'True'
            with open(user_config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nCROSS_FADE_ENABLED=True\n")
            print("Добавлена настройка 'CROSS_FADE_ENABLED=True' в config.txt")

        if 'BOUNCING_ENABLED' not in config_data:
            config_data['BOUNCING_ENABLED'] = 'True'
            with open(user_config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nBOUNCING_ENABLED=True\n")
            print("Добавлена настройка 'BOUNCING_ENABLED=True' в config.txt")

    except Exception as e:
        print(f"ОШИБКА: Не удалось прочитать пользовательский файл настроек '{user_config_file_path}': {e}")
        # Продолжаем, но без пользовательских настроек из этого файла, чтобы не останавливать приложение

    # --- Загрузка и управление APP_CONFIG_FILE (app_config.txt) ---
    app_config_file_path = os.path.join(script_dir, APP_CONFIG_FILE)

    if not os.path.exists(app_config_file_path):
        print(f"Файл настроек приложения '{app_config_file_path}' не найден. Создаю новый файл.")
        try:
            with open(app_config_file_path, 'w', encoding='utf-8') as f:
                f.write("REACTIVE_AUTH_COOKIE=\n")
                f.write("SETUP_COMPLETE=False\n")
                f.write("MODEL_CREATED_COMPLETE=False\n")
                f.write("DRIVER_INSTALL_SUGGESTED=False\n")
            print(f"Файл '{app_config_file_path}' успешно создан.")
        except Exception as e:
            print(f"Критическая ошибка при создании файла '{app_config_file_path}': {e}")
            sys.exit(1)  # Это критическая ошибка, приложение не может работать без этого файла

    try:
        with open(app_config_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line:
                    key, value = line.split('=', 1)
                    config_data[key.strip()] = value.strip()

        # Проверка и добавление новых полей в конфиг приложения, если они отсутствуют
        if 'SETUP_COMPLETE' not in config_data:
            config_data['SETUP_COMPLETE'] = 'False'
            with open(app_config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nSETUP_COMPLETE=False\n")

        if 'MODEL_CREATED_COMPLETE' not in config_data:
            config_data['MODEL_CREATED_COMPLETE'] = 'False'
            with open(app_config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nMODEL_CREATED_COMPLETE=False\n")

        if 'DRIVER_INSTALL_SUGGESTED' not in config_data:
            config_data['DRIVER_INSTALL_SUGGESTED'] = 'False'
            with open(app_config_file_path, 'a', encoding='utf-8') as f:
                f.write("\nDRIVER_INSTALL_SUGGESTED=False\n")

    except Exception as e:
        print(f"Критическая ошибка при чтении файла '{app_config_file_path}': {e}")
        sys.exit(1)  # Это также критическая ошибка

    return config_data


def save_config(config_data):
    """
    Сохраняет весь словарь конфигурации обратно в соответствующие файлы:
    пользовательские настройки в config.txt, настройки приложения в app_config.txt.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_config_file_path = os.path.join(script_dir, USER_CONFIG_FILE)
    app_config_file_path = os.path.join(script_dir, APP_CONFIG_FILE)

    user_data_to_save = {}
    app_data_to_save = {}

    # Разделение данных по файлам
    for key, value in config_data.items():
        if key in ['CAM_FPS', 'CROSS_FADE_ENABLED', 'BOUNCING_ENABLED']:
            user_data_to_save[key] = value
        else:  # Все остальные настройки идут в app_config
            app_data_to_save[key] = value

    try:
        with open(user_config_file_path, 'w', encoding='utf-8') as f:
            for key, value in user_data_to_save.items():
                f.write(f"{key}={value}\n")
        print(f"Пользовательские настройки сохранены в '{user_config_file_path}'.")
    except Exception as e:
        print(f"ОШИБКА: Не удалось сохранить пользовательскую конфигурацию в '{user_config_file_path}': {e}")

    try:
        with open(app_config_file_path, 'w', encoding='utf-8') as f:
            for key, value in app_data_to_save.items():
                f.write(f"{key}={value}\n")
        print(f"Настройки приложения сохранены в '{app_config_file_path}'.")
    except Exception as e:
        print(f"ОШИБКА: Не удалось сохранить конфигурацию приложения в '{app_config_file_path}': {e}")

